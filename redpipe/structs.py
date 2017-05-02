# -*- coding: utf-8 -*-
"""
Experimental code based on patterns I've used elsewhere.
Makes it possible to load data from redis as an object and access the fields.
Then store changes back into redis.
"""
import json
from six import add_metaclass
from .pipelines import pipeline
from .keyspaces import Hash
from .fields import TextField

__all__ = ['Struct']


class StructMeta(type):
    """
    Data binding of a redpipe.Hash to the core of the Struct object.
    Creates it dynamically on class construction.
    uses the _keyspace and _connection fields
    Meta Classes are strange beasts.
    """
    def __new__(mcs, name, bases, d):
        if name in ['Struct']:
            return type.__new__(mcs, name, bases, d)

        class StructHash(Hash):
            _keyspace = d.get('_keyspace', name)
            _connection = d.get('_connection', None)
            _fields = d.get('_fields', {})
            _keyparse = d.get('_keyparse', TextField)
            _valueparse = d.get('_valueparse', TextField)
            _memberparse = d.get('_memberparse', TextField)

        d['core'] = StructHash

        return type.__new__(mcs, name, bases, d)


@add_metaclass(StructMeta)
class Struct(object):
    """
    load and store structured data in redis using OOP patterns.
    """
    __slots__ = ['key', '_data']
    _keyspace = None
    _connection = None
    _fields = {}

    def __init__(self, _key, pipe=None, **kwargs):

        if pipe is None and not kwargs:
            try:
                coerced = dict(_key)
                self.key = coerced['_key']
                del coerced['_key']
                self._data = coerced
                return
            except (ValueError, TypeError, KeyError):
                pass

        self.key = _key
        self._data = {}
        with pipeline(pipe, name=self._connection, autocommit=True) as pipe:
            if kwargs:
                self.change(pipe=pipe, **kwargs)

            ref = self.core(pipe=pipe).hgetall(self.key)

            def cb():
                if not ref.result:
                    return

                for k, v in ref.result.items():
                    self._data[k] = v

            pipe.on_execute(cb)

    def update(self, changes, pipe=None):
        return self.change(pipe=pipe, **changes)

    def change(self, pipe=None, **changes):
        with pipeline(pipe, name=self._connection, autocommit=True) as pipe:
            core = self.core(pipe=pipe)

            def build(k, v):
                if v is None:
                    core.hdel(self.key, k)
                else:
                    core.hset(self.key, k, v)

                def cb():
                    if v is None:
                        try:
                            del self._data[k]
                        except KeyError:
                            pass
                    else:
                        self._data[k] = v

                pipe.on_execute(cb)

            for k, v in changes.items():
                build(k, v)

    def remove(self, fields, pipe=None):
        with pipeline(pipe, name=self._connection, autocommit=True) as pipe:
            core = self.core(pipe=pipe)
            core.hdel(self.key, *fields)

            def cb():
                for k in fields:
                    try:
                        del self._data[k]
                    except KeyError:
                        pass

            pipe.on_execute(cb)

    def copy(self):
        return self.__class__(dict(self))

    @property
    def persisted(self):
        return True if self._data else False

    def clear(self, pipe=None):
        with pipeline(pipe, name=self._connection, autocommit=True) as pipe:
            self.core(pipe=pipe).delete(self.key)

            def cb():
                self._data = {}

            pipe.on_execute(cb)

    def get(self, item, default=None):
        return self._data.get(item, default)

    def __getitem__(self, item):
        if item == '_key':
            return self.key

        return self._data[item]

    def __setitem__(self, key, value):
        self.update({key: value})

    def __delitem__(self, key):
        self.remove([key])

    def __iter__(self):
        for k, v in self.items():
            yield k, v

    def __len__(self):
        return len(dict(self))

    def __contains__(self, item):
        if item == '_key':
            return True
        return item in self._data

    def items(self):
        yield '_key', self.key
        for k, v in self._data.items():
            yield k, v

    iteritems = items

    def __str__(self):
        return "<%s:%s>" % (self.__class__.__name__, self.key)

    def __repr__(self):
        return json.dumps(dict(self))

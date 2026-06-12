# -*- coding: utf-8 -*-
'''
@Time    :   2025/08/18 19:13:04
'''


from libs.wrapper import async_property


class BaseDAO:

    def __init__(self, db: str, conn: str = "mongo"):
        self._db = db
        self._conn = conn
        self._db_map = {}
        self.client = None

    @async_property
    async def client(self):
        from web.component import component
        return await component.get(self._conn).get_client()

    def __getattr__(self, key: str):
        if key not in self._db_map:
            from .orm import DaoHelper
            self._db_map[key] = DaoHelper(self._db, key, self._conn)
        return self._db_map[key]

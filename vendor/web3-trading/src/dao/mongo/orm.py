# -*- coding: utf-8 -*-
'''
@Time    :   2025/08/18 19:30:01
'''


from typing import List, Tuple, Dict, Any

from pymongo import UpdateOne
from pymongo.results import BulkWriteResult, DeleteResult

from libs.wrapper import async_property


class DaoHelper(object):
    _MAX_PAGE_SIZE = 10000
    _MAX_PAGE = 1000

    def __init__(self, db: str, coll: str, name: str = 'default') -> None:
        self.name = name
        self.db = db
        self.coll = coll

    def __getattr__(self, key: str):
        return DaoHelper.__dict__.get(
            key,
            getattr(self.collection, key)
        )

    async def _get_conn(self):
        from web.component import component
        return await component.get(self.name).get_client

    @async_property
    async def collection(self):
        return (await self._get_conn())[self.db][self.coll]

    def _output_name(
        self,
        output_names: List[str],
        hidden_names: List[str]
    ):
        return {
            "_id": True if "_id" in output_names else False,
            **{n: True for n in output_names},
            **{n: False for n in hidden_names},
        }

    async def add_or_update_one(
        self,
        matcher: dict,
        data: dict,
        output_names: List[str] = [],
        hidden_names: List[str] = [],
        **kwargs
    ):
        """新增或更新并返回完整的数据"""
        resp = await (await self.collection).update_one(
            matcher,
            {"$set": data},
            upsert=True,
            **kwargs
        )
        if not bool(resp.raw_result['ok']):
            raise ValueError(f'add or update error, matcher={matcher}')
        return await self.get(
            matcher=matcher,
            output_names=output_names,
            hidden_names=hidden_names,
            **kwargs
        )

    async def add_or_update_one_by_id(
        self,
        data: dict,
        output_names: List[str] = [],
        hidden_names: List[str] = [],
        **kwargs
    ):
        """新增或更新并返回完整的数据"""
        sample_id = data['id']
        resp = await (await self.collection).update_one(
            {"id": sample_id},
            {"$set": data},
            upsert=True,
            **kwargs
        )
        if not bool(resp.raw_result['ok']):
            raise ValueError(f'add or update error, id={sample_id}')
        return await self.get(
            id=sample_id,
            output_names=output_names,
            hidden_names=hidden_names,
            **kwargs
        )

    async def find_and_update(
        self,
        matcher: Dict[str, Any],
        update: Dict[str, Any],
        output_names: List[str] = [],
        hidden_names: List[str] = [],
        resp_doc: bool = True,
        **kwargs
    ):
        """根据条件更新数据"""
        resp = await (await self.collection).update_many(matcher, {"$set": update})
        if resp_doc and resp.raw_result['n']:
            for key in set(matcher.keys()) & set(update.keys()):
                matcher[key] = update[key]
            return await self.query(
                matcher=matcher,
                output_names=output_names,
                hidden_names=hidden_names,
                **kwargs
            )

    async def find_one_and_update_by_id(
        self,
        data: Dict[str, Any],
        output_names: List[str] = [],
        hidden_names: List[str] = [],
        resp_doc: bool = True,
        **kwargs
    ):
        """根据id更新一条数据"""
        projection = self._output_name(output_names, hidden_names)
        return await (await self.collection).find_one_and_update(
            {"id": data["id"]},
            {"$set": data},
            projection=projection,
            return_document=resp_doc,
            **kwargs
        )

    async def batch_add_or_update_by_id(
        self,
        data: List[Dict[str, Any]],
        resp_doc: bool = True,
        output_names: List[str] = [],
        hidden_names: List[str] = [],
        **kwargs
    ) -> BulkWriteResult:
        """批量新增或更新"""
        operations = []
        for row in data:
            operations.append(UpdateOne(
                {"id": row['id']},
                {"$set": row},
                upsert=True,
                **kwargs
            ))
        resp = await (await self.collection).bulk_write(operations)
        if not resp.upserted_count:
            return
        if resp_doc:
            return await self.query(
                {"id": {"$in": [row['id'] for row in data]}},
                output_names=output_names,
                hidden_names=hidden_names
            )

    async def get(
        self,
        id: str = None,
        matcher: dict = {},
        output_names: List[str] = [],
        hidden_names: List[str] = [],
        **kwargs
    ) -> Dict[str, Any]:
        """查询一条数据"""
        if id is not None:
            matcher["id"] = id
        projection = self._output_name(output_names, hidden_names)
        return await (await self.collection).find_one(
            matcher,
            projection=projection,
            **kwargs
        )

    async def query(
        self,
        matcher: dict = {},
        output_names: List[str] = [],
        hidden_names: List[str] = [],
        page: int = 1,
        page_size: int = 0,
        sort: List[Tuple[str, int]] =[],
        **kwargs
    ) -> List:
        """条件查询，默认不分页"""
        page = page if page > 0 else 1
        projection = self._output_name(output_names, hidden_names)
        page = matcher.pop("page", None) or page
        page_size = matcher.pop("pageSize", None) or page_size
        return await (await self.collection).find(
            matcher,
            projection=projection,
            sort=sort,
            **kwargs
        ).skip(page_size * (page - 1)).limit(page_size).to_list(length=None)

    async def query_page(
        self,
        matcher: dict = {},
        page: int = 1,
        page_size: int = 30,
        random=False,
        output_names: List[str] = [],
        hidden_names: List[str] = [],
        sort: List[Tuple[str, int]] = []
    ) -> Dict[str, Any]:
        """分页查询"""
        page_size = min(page_size, self._MAX_PAGE_SIZE)
        skip_docs = (min(page, self._MAX_PAGE) - 1) * page_size
        projection = self._output_name(output_names, hidden_names)

        match_stage = {'$match': matcher}
        project_stage = {"$project": projection}
        if random:
            items_stage = [
                match_stage,
                {"$sample": {"size": page_size}},
                project_stage
            ]
        else:
            if not sort:
                raise
            items_stage = [
                match_stage,
                {"$sort": dict(sort)},
                {"$skip": skip_docs},
                {"$limit": page_size},
                project_stage
            ]

        pipeline = [
            {
                "$facet": {
                    'items': items_stage,
                    'total': [
                        {'$match': matcher},
                        {'$count': 'total'}
                    ]
                }
            },
            {
                "$project": {
                    "items": 1,
                    "total": {
                        "$cond": {
                            "if": {"$gt": [{"$size": "$total"}, 0]},
                            "then": {"$arrayElemAt": ["$total.total", 0]},
                            "else": 0
                        }
                    }
                }
            }
        ]
        return (await (await self.collection).aggregate(pipeline).to_list(length=1))[0]

    async def sample(
        self,
        sample: int,
        matcher: dict = {},
        output_names: List[str] = [],
        hidden_names: List[str] = [],
        sort: List[Tuple[str, int]] = []
    ) -> List[Dict[str, Any]]:
        """
        随机抽样
        sample: 抽样返回的数量
        """
        pipeline = []
        if matcher:
            pipeline.append({'$match': matcher})
        if sort:
            pipeline.append({'$sort': dict(sort)})
        projection = self._output_name(output_names, hidden_names)
        pipeline.append({"$project": projection})
        pipeline.append({'$sample': {'size': sample}})
        return await (await self.collection).aggregate(pipeline).to_list(length=None)

    async def insert_many(self, data: List[Dict[str, Any]], **kwargs):
        """批量插入文档（append-only，不做 upsert）"""
        if not data:
            return
        return await (await self.collection).insert_many(data, **kwargs)

    async def count(self, matcher: dict = {}) -> int:
        return await (await self.collection).count_documents(matcher)

    async def delete(
        self,
        id: str = None,
        matcher: dict = {}
    ) -> DeleteResult:
        if id is not None:
            matcher.update({"id": id})
        if not matcher:
            return
        return await (await self.collection).delete_one(matcher)

    async def batch_delete(self, matcher: dict = {}) -> int:
        resp = await (await self.collection).delete_many(matcher)
        return resp.raw_result['n']

    async def distinct(self, key: str, matcher: dict = {}) -> List:
        return await (await self.collection).find(matcher).distinct(key)

    async def aggregate(
        self,
        pipeline: List = [],
        output_names: List[str] = [],
        hidden_names: List[str] = [],
        page: int = 1,
        page_size: int = 0
    ) -> List:
        if page > 1:
            pipeline.append({'$skip': page_size * (page - 1)})
        if page_size > 0:
            pipeline.append({'$limit': page_size})
        projection = self._output_name(output_names, hidden_names)
        pipeline.append({"$project": projection})
        return await (await self.collection).aggregate(pipeline, allowDiskUse=True).to_list(length=None)

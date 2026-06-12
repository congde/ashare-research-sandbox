# -*- coding: utf-8 -*-
'''
@Time    :   2025/08/20 11:28:18
Root (/) and /dashboard are registered in web.application.create_app() to avoid
FastAPI prefix="/" validation issues. This module is kept for compatibility with auto_import.
'''
import logging

from web.router import BaseRouter

logger = logging.getLogger(__name__)


class IndexApi(BaseRouter):
    """Placeholder: / and /dashboard are registered in application.create_app()."""

    def __init__(self):
        super().__init__(prefix="/")

"""MySQL 输入适配器：从 MySQL 表读取原始文章作为数据来源。

连接参数优先级：显式参数 > config["mysql"] > 环境变量 MYSQL_*。
依赖（可选）：pip install pymysql 或 pip install "data-to-article[mysql]"
"""

from __future__ import annotations

import os

from data_to_article.ingest.base import IngestSource


class MySqlIngest(IngestSource):
    def __init__(self, host: str = "", port: int = 0, user: str = "",
                 password: str = "", database: str = "", table: str = "",
                 where: str = "", **kwargs):
        try:
            import pymysql
        except ImportError:
            raise RuntimeError(
                "MySQL 输入需要 pymysql：pip install pymysql "
                "（或 pip install 'data-to-article[mysql]'）"
            )
        self.host = host or os.environ.get("MYSQL_HOST", "localhost")
        self.port = int(port or os.environ.get("MYSQL_PORT", "3306"))
        self.user = user or os.environ.get("MYSQL_USER", "root")
        self.password = password or os.environ.get("MYSQL_PASSWORD", "")
        self.database = database or os.environ.get("MYSQL_DB", "")
        self.table = table or os.environ.get("MYSQL_TABLE", "")
        if not self.database or not self.table:
            raise ValueError("MySQL 输入需要 MYSQL_DB 与 MYSQL_TABLE（或 config 的 mysql.database/table）")
        self.where = where or os.environ.get("MYSQL_WHERE", "")
        self._conn = pymysql.connect(
            host=self.host,
            port=self.port,
            user=self.user,
            password=self.password,
            database=self.database,
            charset="utf8mb4",
            cursorclass=pymysql.cursors.DictCursor,
        )

    def read(self, limit: int = 0) -> list[dict]:
        sql = f"SELECT * FROM `{self.table}`"
        if self.where:
            sql += f" WHERE {self.where}"
        if limit > 0:
            sql += f" LIMIT {limit}"
        with self._conn.cursor() as cur:
            cur.execute(sql)
            rows = cur.fetchall()
        return [dict(r) for r in rows]
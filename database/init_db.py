# -*- coding: utf-8 -*-
"""初始化数据库：建表并从 JSON 灌入营养库与菜谱库。

用法：在项目根目录执行  python database/init_db.py
"""
import os
import sys

# 确保项目根目录在 sys.path 中，便于 `import database` / `import config`
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import database.db as db


def main():
    conn = db.get_connection()
    db.create_tables(conn)
    n_ing, n_rec = db.seed_from_json(conn)
    conn.close()
    print(f"数据库初始化完成：食材 {n_ing} 条，菜谱 {n_rec} 条")


if __name__ == "__main__":
    main()

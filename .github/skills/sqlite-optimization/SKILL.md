---
name: sqlite-optimization
description: 'SQLite performance optimization assistant specializing in Python environments. Focuses on query tuning, indexing strategies, PRAGMA optimizations, concurrency management, and execution plan analysis using sqlite3, SQLAlchemy, and pandas.'
---

# SQLite Performance Optimization Assistant

Expert SQLite performance optimization for ${selection} (or entire project if no selection). Focus on SQLite-specific optimization techniques and their seamless integration within Python environments.

## 🎯 Core Optimization Areas

### Concurrency & PRAGMA Tuning
```sql
-- ❌ BAD: Default SQLite settings 
-- Prone to "database is locked" errors during concurrent Python thread access.

-- ✅ GOOD: Optimized PRAGMAs for performance and concurrency
PRAGMA journal_mode = WAL;       -- Write-Ahead Logging for simultaneous readers and a writer
PRAGMA synchronous = NORMAL;     -- Balances safety and write speed in WAL mode
PRAGMA foreign_keys = ON;        -- Enforce foreign key constraints
PRAGMA cache_size = -64000;      -- Allocate ~64MB for page caching
```

### Python Batch Operations
```python
# ❌ BAD: Row-by-row operations in Python (Huge overhead)
for item in data:
    cursor.execute("INSERT INTO products (name, price) VALUES (?, ?)", (item.name, item.price))

# ✅ GOOD: Batch execution using standard sqlite3
cursor.executemany("INSERT INTO products (name, price) VALUES (?, ?)", data_tuples)

# ✅ GOOD: SQLAlchemy Core bulk inserts
conn.execute(products_table.insert(), data_dictionaries)

# ✅ GOOD: Pandas fast insertion
df.to_sql('products', con=engine, if_exists='append', index=False, method='multi', chunksize=1000)
```

### Index Strategy Optimization
```sql
-- ❌ BAD: Poor indexing strategy
CREATE INDEX idx_user_data ON users(email, first_name, last_name, created_at);

-- ✅ GOOD: Optimized composite indexing (Left-to-right matching)
CREATE INDEX idx_users_email_created ON users(email, created_at);

-- ✅ GOOD: Partial Indexing (Saves space and improves specific query speed)
CREATE INDEX idx_users_status_created ON users(status, created_at)
WHERE status = 'active';
```

## 📊 Performance Tuning Techniques

### Pagination Optimization
```sql
-- ❌ BAD: OFFSET-based pagination (Slows down as offset grows)
SELECT * FROM products 
ORDER BY created_at DESC 
LIMIT 20 OFFSET 10000;

-- ✅ GOOD: Cursor-based pagination (using Indexed columns)
SELECT * FROM products 
WHERE created_at < '2024-06-15 10:30:00'
ORDER BY created_at DESC 
LIMIT 20;
```

### Subquery & Aggregation Optimization
```sql
-- ❌ BAD: Correlated subquery executing per row
SELECT p.product_name, p.price
FROM products p
WHERE p.price > (
    SELECT AVG(price) FROM products p2 WHERE p2.category_id = p.category_id
);

-- ✅ GOOD: Window function approach (Supported in SQLite 3.25.0+)
SELECT product_name, price
FROM (
    SELECT product_name, price,
           AVG(price) OVER (PARTITION BY category_id) as avg_category_price
    FROM products
) ranked
WHERE price > avg_category_price;
```

## 🔍 Query Anti-Patterns

### SELECT & WHERE Clause Issues
```sql
-- ❌ BAD: SELECT * and using functions in WHERE clause that break indexes
SELECT * FROM orders 
WHERE UPPER(customer_email) = 'JOHN@EXAMPLE.COM';

-- ✅ GOOD: Explicit columns and index-friendly filtering
SELECT id, total_amount FROM orders 
WHERE customer_email = 'john@example.com';
-- Define column as NOCASE for case-insensitive matching:
-- email TEXT COLLATE NOCASE
```

### IN vs EXISTS
```sql
-- ❌ BAD: Large IN clauses
SELECT * FROM orders WHERE customer_id IN (SELECT id FROM customers WHERE status = 'inactive');

-- ✅ GOOD: EXISTS for correlated checks (often faster in SQLite query planner)
SELECT o.* FROM orders o 
WHERE EXISTS (
    SELECT 1 FROM customers c 
    WHERE c.id = o.customer_id AND c.status = 'inactive'
);
```

## 📈 Database-Agnostic / Python Specific Optimization

### Transaction Management
```python
# ❌ BAD: Committing inside a loop
for row in dataset:
    cursor.execute("UPDATE inventory SET qty = ? WHERE id = ?", (row.qty, row.id))
    conn.commit() # Forces a disk sync every time

# ✅ GOOD: Wrap in a single transaction block
try:
    cursor.execute("BEGIN TRANSACTION;")
    cursor.executemany("UPDATE inventory SET qty = ? WHERE id = ?", updates)
    conn.commit()
except sqlite3.Error:
    conn.rollback()
```

## 📊 Performance Monitoring & Profiling

### Analyzing Queries
```sql
-- Prefix any complex query with EXPLAIN QUERY PLAN to see how SQLite executes it
EXPLAIN QUERY PLAN 
SELECT o.id, c.name FROM orders o 
INNER JOIN customers c ON o.customer_id = c.id 
WHERE o.created_at > '2024-01-01';
-- Look for "SCAN TABLE" (bad, full table scan) vs "SEARCH TABLE" (good, index used)
```

### Python-Level Profiling
```python
# ✅ GOOD: Trace all SQL statements executed by the connection
import sqlite3

def trace_callback(statement):
    print(f"Executing: {statement}")

conn = sqlite3.connect('app.db')
conn.set_trace_callback(trace_callback)

# ✅ GOOD: SQLAlchemy Echo for ORM query inspection
from sqlalchemy import create_engine
engine = create_engine('sqlite:///app.db', echo=True)
```

## 🎯 Universal Optimization Checklist

### Query & DB Structure
- [ ] Enabled `PRAGMA journal_mode=WAL` for concurrent reads/writes.
- [ ] Explicitly managing transactions with `BEGIN` and `COMMIT`.
- [ ] Avoiding `SELECT *` in production code.
- [ ] Reviewing execution plans using `EXPLAIN QUERY PLAN`.

### Index Strategy
- [ ] Creating covering indexes for high-frequency queries.
- [ ] Utilizing partial indexes (`WHERE` clause in index definition) to save DB file size.
- [ ] Applying proper `COLLATE` (e.g., `NOCASE`) at schema creation to avoid function calls in queries.

### Python Integration
- [ ] Replaced repetitive `execute` calls with `executemany`.
- [ ] Leveraged `pandas.to_sql(method='multi')` for dataframe ingestion.
- [ ] Validating that Alembic/SQLAlchemy migrations include proper index creation.
- [ ] Handling "database is locked" errors gracefully with appropriate `timeout` values in `sqlite3.connect()`.
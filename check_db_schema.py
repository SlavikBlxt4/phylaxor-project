import psycopg2
import os

DSN = "dbname=phylaxor user=postgres password=postgres host=localhost port=15432"

def check_schema():
    try:
        conn = psycopg2.connect(DSN)
        cur = conn.cursor()
        
        print("Connected to database successfully.")
        
        tables = ['decisions', 'alerts']
        for t in tables:
            print(f"\nChecking table: {t}")
            cur.execute("""
                SELECT column_name, data_type 
                FROM information_schema.columns 
                WHERE table_name = %s 
                ORDER BY column_name;
            """, (t,))
            
            rows = cur.fetchall()
            if not rows:
                print(f"  [ERROR] Table {t} NOT FOUND!")
                continue
                
            for col, dtype in rows:
                print(f"  - {col} ({dtype})")
                
        conn.close()
        
    except Exception as e:
        print(f"Connection failed: {e}")

if __name__ == "__main__":
    check_schema()

from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel
from typing import Optional, List
import sqlite3
import json
import calendar as cal
from contextlib import contextmanager
from pathlib import Path
from datetime import date, timedelta, datetime

app = FastAPI(title="Casa")
DB_PATH = Path(__file__).parent / "household.db"
STATIC_DIR = Path(__file__).parent / "static"

# ─── DB ─────────────────────────────────────────────────────────────────


@contextmanager
def db():
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db():
    with db() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS members (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                name       TEXT    NOT NULL UNIQUE,
                color      TEXT    NOT NULL DEFAULT '#a78bfa',
                emoji      TEXT    NOT NULL DEFAULT '✨',
                created_at TEXT    NOT NULL DEFAULT (datetime('now'))
            );
            CREATE TABLE IF NOT EXISTS expenses (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                description TEXT    NOT NULL,
                amount      REAL    NOT NULL,
                paid_by     INTEGER NOT NULL REFERENCES members(id) ON DELETE CASCADE,
                category    TEXT    NOT NULL DEFAULT 'general',
                notes       TEXT,
                date        TEXT    NOT NULL DEFAULT (date('now')),
                created_at  TEXT    NOT NULL DEFAULT (datetime('now'))
            );
            CREATE TABLE IF NOT EXISTS expense_splits (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                expense_id INTEGER NOT NULL REFERENCES expenses(id) ON DELETE CASCADE,
                member_id  INTEGER NOT NULL REFERENCES members(id) ON DELETE CASCADE,
                amount     REAL    NOT NULL
            );
            CREATE TABLE IF NOT EXISTS settlements (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                from_member INTEGER NOT NULL REFERENCES members(id) ON DELETE CASCADE,
                to_member   INTEGER NOT NULL REFERENCES members(id) ON DELETE CASCADE,
                amount      REAL    NOT NULL,
                note        TEXT,
                date        TEXT    NOT NULL DEFAULT (date('now')),
                created_at  TEXT    NOT NULL DEFAULT (datetime('now'))
            );
            CREATE TABLE IF NOT EXISTS recurring_expenses (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                description TEXT    NOT NULL,
                amount      REAL    NOT NULL,
                paid_by     INTEGER NOT NULL REFERENCES members(id) ON DELETE CASCADE,
                category    TEXT    NOT NULL DEFAULT 'general',
                frequency   TEXT    NOT NULL DEFAULT 'monthly',
                next_due    TEXT    NOT NULL,
                split_type  TEXT    NOT NULL DEFAULT 'equal',
                member_ids  TEXT    NOT NULL DEFAULT '[]',
                is_active   INTEGER NOT NULL DEFAULT 1,
                created_at  TEXT    NOT NULL DEFAULT (datetime('now'))
            );
            CREATE TABLE IF NOT EXISTS chores (
                id             INTEGER PRIMARY KEY AUTOINCREMENT,
                name           TEXT    NOT NULL,
                category       TEXT    NOT NULL DEFAULT 'general',
                icon           TEXT    NOT NULL DEFAULT '🧹',
                frequency      TEXT    NOT NULL DEFAULT 'weekly',
                rotation_order TEXT    NOT NULL DEFAULT '[]',
                rotation_index INTEGER NOT NULL DEFAULT 0,
                is_active      INTEGER NOT NULL DEFAULT 1,
                created_at     TEXT    NOT NULL DEFAULT (datetime('now'))
            );
            CREATE TABLE IF NOT EXISTS chore_completions (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                chore_id     INTEGER NOT NULL REFERENCES chores(id) ON DELETE CASCADE,
                member_id    INTEGER NOT NULL REFERENCES members(id) ON DELETE CASCADE,
                completed_at TEXT    NOT NULL DEFAULT (datetime('now')),
                notes        TEXT
            );
            CREATE TABLE IF NOT EXISTS events (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                title        TEXT    NOT NULL,
                description  TEXT,
                event_date   TEXT    NOT NULL,
                event_time   TEXT,
                created_by   INTEGER REFERENCES members(id) ON DELETE SET NULL,
                color        TEXT,
                location     TEXT,
                created_at   TEXT    NOT NULL DEFAULT (datetime('now'))
            );
            CREATE TABLE IF NOT EXISTS event_rsvps (
                event_id  INTEGER NOT NULL REFERENCES events(id) ON DELETE CASCADE,
                member_id INTEGER NOT NULL REFERENCES members(id) ON DELETE CASCADE,
                status    TEXT    NOT NULL DEFAULT 'pending',
                PRIMARY KEY (event_id, member_id)
            );
        """)
        # Safe migration: add notes column if missing (older DBs)
        try:
            conn.execute("ALTER TABLE expenses ADD COLUMN notes TEXT")
        except Exception:
            pass


init_db()

# ─── Models ─────────────────────────────────────────────────────────────


def rows(cur): return [dict(r) for r in cur.fetchall()]


class MemberIn(BaseModel):
    name: str
    color: str = '#a78bfa'
    emoji: str = '✨'


class MemberPatch(BaseModel):
    name: Optional[str] = None
    color: Optional[str] = None
    emoji: Optional[str] = None


class SplitIn(BaseModel):
    member_id: int
    amount: float


class ExpenseIn(BaseModel):
    description: str
    amount: float
    paid_by: int
    category: str = 'general'
    notes: Optional[str] = None
    date: str = ''
    splits: List[SplitIn]


class SettlementIn(BaseModel):
    from_member: int
    to_member: int
    amount: float
    note: Optional[str] = None


class RecurringIn(BaseModel):
    description: str
    amount: float
    paid_by: int
    category: str = 'general'
    frequency: str = 'monthly'
    next_due: str = ''
    member_ids: List[int] = []


class ChoreIn(BaseModel):
    name: str
    category: str = 'general'
    icon: str = '🧹'
    frequency: str = 'weekly'
    member_ids: Optional[List[int]] = None


class CompleteChoreIn(BaseModel):
    member_id: int
    notes: Optional[str] = None


class EventIn(BaseModel):
    title: str
    description: Optional[str] = None
    event_date: str
    event_time: Optional[str] = None
    created_by: Optional[int] = None
    color: Optional[str] = None
    location: Optional[str] = None


class EventPatch(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    event_date: Optional[str] = None
    event_time: Optional[str] = None
    color: Optional[str] = None
    location: Optional[str] = None


class RsvpIn(BaseModel):
    member_id: int
    status: str

# ─── Balance helpers ────────────────────────────────────────────────────


def compute_balances(conn):
    members = {r['id']: dict(r) for r in conn.execute("SELECT * FROM members")}
    if not members:
        return [], []

    net = {mid: 0.0 for mid in members}

    for r in conn.execute(
            "SELECT paid_by, SUM(amount) as t FROM expenses GROUP BY paid_by"):
        if r['paid_by'] in net:
            net[r['paid_by']] += r['t']

    for r in conn.execute(
            "SELECT member_id, SUM(amount) as t FROM expense_splits GROUP BY member_id"):
        if r['member_id'] in net:
            net[r['member_id']] -= r['t']

    for r in conn.execute(
            "SELECT from_member, to_member, amount FROM settlements"):
        if r['from_member'] in net:
            net[r['from_member']] += r['amount']
        if r['to_member'] in net:
            net[r['to_member']] -= r['amount']

    EPSILON = 0.01
    creditors = sorted([(mid, v) for mid, v in net.items()
                       if v > EPSILON], key=lambda x: -x[1])
    debtors = sorted([(mid, -v) for mid, v in net.items()
                     if v < -EPSILON], key=lambda x: -x[1])

    txns, ci, di = [], 0, 0
    while ci < len(creditors) and di < len(debtors):
        cid, c = creditors[ci]
        did, d = debtors[di]
        amt = min(c, d)
        txns.append({
            'from_id': did, 'from_name': members[did]['name'],
            'from_emoji': members[did]['emoji'], 'from_color': members[did]['color'],
            'to_id': cid, 'to_name': members[cid]['name'],
            'to_emoji': members[cid]['emoji'], 'to_color': members[cid]['color'],
            'amount': round(amt, 2)
        })
        creditors[ci] = (cid, round(c - amt, 2))
        debtors[di] = (did, round(d - amt, 2))
        if creditors[ci][1] < EPSILON:
            ci += 1
        if debtors[di][1] < EPSILON:
            di += 1

    net_list = [{'id': mid,
                 'name': members[mid]['name'],
                 'emoji': members[mid]['emoji'],
                 'color': members[mid]['color'],
                 'net': round(b,
                              2)} for mid,
                b in net.items()]
    return net_list, txns

# ─── Chore helpers ──────────────────────────────────────────────────────


FREQ_DAYS = {'daily': 1, 'weekly': 7, 'biweekly': 14, 'monthly': 30}


def chore_due_info(chore_dict, conn):
    last = conn.execute(
        "SELECT completed_at FROM chore_completions WHERE chore_id=? ORDER BY completed_at DESC LIMIT 1",
        (chore_dict['id'],)).fetchone()
    base_date = (date.fromisoformat(last['completed_at'][:10]) if last else date.today(
    ) - timedelta(days=FREQ_DAYS[chore_dict['frequency']]))
    due = base_date + timedelta(days=FREQ_DAYS[chore_dict['frequency']])
    days = (due - date.today()).days
    status = 'overdue' if days < 0 else 'due_today' if days == 0 else 'upcoming'
    return {
        'due_date': due.isoformat(),
        'days_until_due': days,
        'status': status}


def get_current_assignee(chore_dict, conn):
    rotation = json.loads(chore_dict['rotation_order'])
    if not rotation:
        return None
    mid = rotation[chore_dict['rotation_index'] % len(rotation)]
    r = conn.execute("SELECT * FROM members WHERE id=?", (mid,)).fetchone()
    return dict(r) if r else None


def enrich_chore(c, conn):
    return {
        **c, 'current_assignee': get_current_assignee(c, conn), **chore_due_info(c, conn)}

# ─── Members ────────────────────────────────────────────────────────────


@app.get("/api/members")
def list_members():
    with db() as conn:
        return rows(conn.execute("SELECT * FROM members ORDER BY name"))


@app.post("/api/members", status_code=201)
def create_member(data: MemberIn):
    with db() as conn:
        try:
            cur = conn.execute(
                "INSERT INTO members (name,color,emoji) VALUES (?,?,?)",
                (data.name,
                 data.color,
                 data.emoji))
            return dict(
                conn.execute(
                    "SELECT * FROM members WHERE id=?",
                    (cur.lastrowid,
                     )).fetchone())
        except sqlite3.IntegrityError:
            raise HTTPException(400, "Name already taken")


@app.post("/api/members/bulk", status_code=201)
def bulk_create_members(data: List[MemberIn]):
    created = []
    with db() as conn:
        for m in data:
            try:
                cur = conn.execute(
                    "INSERT INTO members (name,color,emoji) VALUES (?,?,?)",
                    (m.name,
                     m.color,
                     m.emoji))
                created.append(
                    dict(
                        conn.execute(
                            "SELECT * FROM members WHERE id=?",
                            (cur.lastrowid,
                             )).fetchone()))
            except sqlite3.IntegrityError:
                existing = conn.execute(
                    "SELECT * FROM members WHERE name=?", (m.name,)).fetchone()
                if existing:
                    created.append(dict(existing))
    return created


@app.put("/api/members/{id}")
def update_member(id: int, data: MemberPatch):
    with db() as conn:
        if not conn.execute(
                "SELECT 1 FROM members WHERE id=?", (id,)).fetchone():
            raise HTTPException(404)
        fields = {k: v for k, v in data.dict().items() if v is not None}
        if fields:
            conn.execute(
                f"UPDATE members SET {', '.join(f'{k}=?' for k in fields)} WHERE id=?",
                (*fields.values(), id))
        return dict(
            conn.execute(
                "SELECT * FROM members WHERE id=?", (id,)).fetchone())


@app.delete("/api/members/{id}", status_code=204)
def delete_member(id: int):
    with db() as conn:
        conn.execute("DELETE FROM members WHERE id=?", (id,))

# ─── Expenses ───────────────────────────────────────────────────────────


@app.get("/api/expenses")
def list_expenses():
    with db() as conn:
        exps = rows(conn.execute("""
            SELECT e.*, m.name as payer_name, m.emoji as payer_emoji, m.color as payer_color
            FROM expenses e JOIN members m ON e.paid_by = m.id
            ORDER BY e.date DESC, e.created_at DESC
        """))
        for e in exps:
            e['splits'] = rows(conn.execute("""
                SELECT s.*, m.name, m.emoji, m.color FROM expense_splits s
                JOIN members m ON s.member_id = m.id WHERE s.expense_id=?
            """, (e['id'],)))
        return exps


@app.post("/api/expenses", status_code=201)
def create_expense(data: ExpenseIn):
    total = round(sum(s.amount for s in data.splits), 2)
    if abs(total - data.amount) > 0.02:
        raise HTTPException(
            400, f"Splits total ${total:.2f} ≠ expense ${data.amount:.2f}")
    exp_date = data.date or str(date.today())
    with db() as conn:
        cur = conn.execute(
            "INSERT INTO expenses (description,amount,paid_by,category,notes,date) VALUES (?,?,?,?,?,?)",
            (data.description, data.amount, data.paid_by, data.category, data.notes, exp_date))
        eid = cur.lastrowid
        for s in data.splits:
            conn.execute(
                "INSERT INTO expense_splits (expense_id,member_id,amount) VALUES (?,?,?)",
                (eid,
                 s.member_id,
                 s.amount))
        return dict(
            conn.execute(
                "SELECT * FROM expenses WHERE id=?", (eid,)).fetchone())


@app.delete("/api/expenses/{id}", status_code=204)
def delete_expense(id: int):
    with db() as conn:
        conn.execute("DELETE FROM expenses WHERE id=?", (id,))


@app.get("/api/balances")
def get_balances():
    with db() as conn:
        net_list, txns = compute_balances(conn)
        total = conn.execute(
            "SELECT COALESCE(SUM(amount),0) as t FROM expenses").fetchone()['t']
        return {
            "net_balances": net_list,
            "simplified_debts": txns,
            "total_spent": round(
                total,
                2)}


@app.post("/api/settlements", status_code=201)
def create_settlement(data: SettlementIn):
    with db() as conn:
        cur = conn.execute(
            "INSERT INTO settlements (from_member,to_member,amount,note) VALUES (?,?,?,?)",
            (data.from_member, data.to_member, data.amount, data.note))
        row = dict(
            conn.execute(
                "SELECT * FROM settlements WHERE id=?",
                (cur.lastrowid,
                 )).fetchone())
        fm = conn.execute("SELECT * FROM members WHERE id=?",
                          (data.from_member,)).fetchone()
        tm = conn.execute("SELECT * FROM members WHERE id=?",
                          (data.to_member,)).fetchone()
        row['from_name'] = fm['name'] if fm else ''
        row['from_emoji'] = fm['emoji'] if fm else ''
        row['to_name'] = tm['name'] if tm else ''
        row['to_emoji'] = tm['emoji'] if tm else ''
        return row


@app.get("/api/settlements")
def list_settlements():
    with db() as conn:
        return rows(conn.execute("""
            SELECT s.*, f.name as from_name, f.emoji as from_emoji, f.color as from_color,
                   t.name as to_name, t.emoji as to_emoji, t.color as to_color
            FROM settlements s
            JOIN members f ON s.from_member=f.id
            JOIN members t ON s.to_member=t.id
            ORDER BY s.created_at DESC
        """))

# ─── Monthly summary ────────────────────────────────────────────────────


@app.get("/api/summary")
def get_summary(year: int = 0, month: int = 0):
    if not year or not month:
        today = date.today()
        year, month = today.year, today.month
    last_day = cal.monthrange(year, month)[1]
    start = f"{year:04d}-{month:02d}-01"
    end = f"{year:04d}-{month:02d}-{last_day:02d}"
    with db() as conn:
        exps = rows(conn.execute(
            "SELECT * FROM expenses WHERE date BETWEEN ? AND ?", (start, end)))
        total = sum(e['amount'] for e in exps)

        # Category breakdown
        cat_map = {}
        for e in exps:
            cat_map[e['category']] = round(
                cat_map.get(e['category'], 0) + e['amount'], 2)

        # Per-member share (sum of their splits this month)
        members = rows(conn.execute("SELECT * FROM members"))
        member_shares = []
        for m in members:
            splits = conn.execute("""
                SELECT COALESCE(SUM(es.amount),0) as t FROM expense_splits es
                JOIN expenses e ON es.expense_id=e.id
                WHERE es.member_id=? AND e.date BETWEEN ? AND ?
            """, (m['id'], start, end)).fetchone()['t']
            paid = conn.execute(
                "SELECT COALESCE(SUM(amount),0) as t FROM expenses WHERE paid_by=? AND date BETWEEN ? AND ?",
                (m['id'], start, end)).fetchone()['t']
            member_shares.append(
                {**m, 'share': round(splits, 2), 'paid': round(paid, 2)})

        # Biggest expense
        biggest = None
        if exps:
            biggest = max(exps, key=lambda e: e['amount'])

        # Most active spender
        spender = max(member_shares, key=lambda m: m['paid'], default=None)

        return {
            'year': year, 'month': month,
            'total': round(total, 2),
            'expense_count': len(exps),
            'category_breakdown': cat_map,
            'member_shares': member_shares,
            'biggest_expense': biggest,
            'most_active_spender': spender,
        }

# ─── Recurring expenses ─────────────────────────────────────────────────


@app.get("/api/recurring")
def list_recurring():
    with db() as conn:
        recs = rows(conn.execute("""
            SELECT r.*, m.name as payer_name, m.emoji as payer_emoji, m.color as payer_color
            FROM recurring_expenses r JOIN members m ON r.paid_by=m.id
            WHERE r.is_active=1 ORDER BY r.next_due
        """))
        return recs


@app.post("/api/recurring", status_code=201)
def create_recurring(data: RecurringIn):
    next_due = data.next_due or str(date.today())
    with db() as conn:
        member_ids = data.member_ids or [
            r['id'] for r in conn.execute("SELECT id FROM members").fetchall()]
        cur = conn.execute(
            "INSERT INTO recurring_expenses (description,amount,paid_by,category,frequency,next_due,member_ids) VALUES (?,?,?,?,?,?,?)",
            (data.description,
             data.amount,
             data.paid_by,
             data.category,
             data.frequency,
             next_due,
             json.dumps(member_ids)))
        return dict(
            conn.execute(
                "SELECT * FROM recurring_expenses WHERE id=?",
                (cur.lastrowid,
                 )).fetchone())


@app.delete("/api/recurring/{id}", status_code=204)
def delete_recurring(id: int):
    with db() as conn:
        conn.execute(
            "UPDATE recurring_expenses SET is_active=0 WHERE id=?", (id,))


@app.post("/api/recurring/{id}/trigger")
def trigger_recurring(id: int):
    with db() as conn:
        rec = conn.execute(
            "SELECT * FROM recurring_expenses WHERE id=?", (id,)).fetchone()
        if not rec:
            raise HTTPException(404)
        rec = dict(rec)
        member_ids = json.loads(rec['member_ids'])
        if not member_ids:
            member_ids = [r['id'] for r in conn.execute(
                "SELECT id FROM members").fetchall()]
        n = len(member_ids)
        base = round(rec['amount'] / n, 2) if n else rec['amount']
        rem = round(rec['amount'] - base * n, 2)
        splits = [{'member_id': mid, 'amount': base + (rem if i == 0 else 0)}
                  for i, mid in enumerate(member_ids)]
        total = round(sum(s['amount'] for s in splits), 2)
        if abs(total - rec['amount']) > 0.02:
            splits[0]['amount'] = round(
                splits[0]['amount'] + rec['amount'] - total, 2)

        cur = conn.execute(
            "INSERT INTO expenses (description,amount,paid_by,category,date) VALUES (?,?,?,?,?)",
            (rec['description'], rec['amount'], rec['paid_by'], rec['category'], str(date.today())))
        eid = cur.lastrowid
        for s in splits:
            conn.execute(
                "INSERT INTO expense_splits (expense_id,member_id,amount) VALUES (?,?,?)",
                (eid,
                 s['member_id'],
                    s['amount']))

        # Advance next_due
        freq_delta = {'daily': 1, 'weekly': 7, 'monthly': 30}
        delta = freq_delta.get(rec['frequency'], 30)
        next_due = (
            date.fromisoformat(
                rec['next_due']) +
            timedelta(
                days=delta)).isoformat()
        conn.execute(
            "UPDATE recurring_expenses SET next_due=? WHERE id=?", (next_due, id))

        exp = dict(
            conn.execute(
                "SELECT * FROM expenses WHERE id=?", (eid,)).fetchone())
        exp['splits'] = splits
        return exp

# ─── Export / Import ────────────────────────────────────────────────────


@app.get("/api/export")
def export_data():
    with db() as conn:
        exps = rows(conn.execute("""
            SELECT e.*, m.name as payer_name FROM expenses e JOIN members m ON e.paid_by=m.id
            ORDER BY e.date DESC
        """))
        for e in exps:
            e['splits'] = rows(conn.execute("""
                SELECT s.amount, m.name FROM expense_splits s JOIN members m ON s.member_id=m.id
                WHERE s.expense_id=?
            """, (e['id'],)))
        data = {
            'exported_at': datetime.now().isoformat(),
            'members': rows(
                conn.execute("SELECT * FROM members ORDER BY name")),
            'expenses': exps,
            'settlements': rows(
                conn.execute("""
                SELECT s.*, f.name as from_name, t.name as to_name FROM settlements s
                JOIN members f ON s.from_member=f.id JOIN members t ON s.to_member=t.id
                ORDER BY s.date DESC
            """)),
            'recurring': rows(
                conn.execute("SELECT * FROM recurring_expenses WHERE is_active=1")),
            'chores': rows(
                conn.execute("SELECT * FROM chores WHERE is_active=1")),
            'events': rows(
                conn.execute("SELECT * FROM events ORDER BY event_date")),
        }
    return JSONResponse(
        content=data, headers={
            "Content-Disposition": f'attachment; filename="casa_export_{date.today()}.json"'})

# ─── Chores ─────────────────────────────────────────────────────────────


@app.get("/api/chores")
def list_chores():
    with db() as conn:
        chore_list = rows(
            conn.execute("SELECT * FROM chores WHERE is_active=1 ORDER BY category, name"))
        return [enrich_chore(c, conn) for c in chore_list]


@app.post("/api/chores", status_code=201)
def create_chore(data: ChoreIn):
    with db() as conn:
        member_ids = data.member_ids or [r['id'] for r in conn.execute(
            "SELECT id FROM members ORDER BY name").fetchall()]
        cur = conn.execute(
            "INSERT INTO chores (name,category,icon,frequency,rotation_order) VALUES (?,?,?,?,?)",
            (data.name, data.category, data.icon, data.frequency, json.dumps(member_ids)))
        c = dict(
            conn.execute(
                "SELECT * FROM chores WHERE id=?",
                (cur.lastrowid,
                 )).fetchone())
        return enrich_chore(c, conn)


@app.put("/api/chores/{id}")
def update_chore(id: int, data: ChoreIn):
    with db() as conn:
        if not conn.execute(
                "SELECT 1 FROM chores WHERE id=?", (id,)).fetchone():
            raise HTTPException(404)
        member_ids = data.member_ids or [r['id'] for r in conn.execute(
            "SELECT id FROM members ORDER BY name").fetchall()]
        conn.execute(
            "UPDATE chores SET name=?,category=?,icon=?,frequency=?,rotation_order=? WHERE id=?",
            (data.name, data.category, data.icon, data.frequency, json.dumps(member_ids), id))
        c = dict(
            conn.execute(
                "SELECT * FROM chores WHERE id=?", (id,)).fetchone())
        return enrich_chore(c, conn)


@app.delete("/api/chores/{id}", status_code=204)
def delete_chore(id: int):
    with db() as conn:
        conn.execute("UPDATE chores SET is_active=0 WHERE id=?", (id,))


@app.post("/api/chores/{id}/complete")
def complete_chore(id: int, data: CompleteChoreIn):
    with db() as conn:
        chore = conn.execute(
            "SELECT * FROM chores WHERE id=?", (id,)).fetchone()
        if not chore:
            raise HTTPException(404)
        chore = dict(chore)
        rotation = json.loads(chore['rotation_order'])
        new_idx = (chore['rotation_index'] + 1) % max(len(rotation), 1)
        conn.execute(
            "INSERT INTO chore_completions (chore_id,member_id,notes) VALUES (?,?,?)",
            (id,
             data.member_id,
             data.notes))
        conn.execute(
            "UPDATE chores SET rotation_index=? WHERE id=?", (new_idx, id))
        next_assignee = None
        if rotation:
            r = conn.execute("SELECT * FROM members WHERE id=?",
                             (rotation[new_idx],)).fetchone()
            if r:
                next_assignee = dict(r)
        return {"completed": True, "next_assignee": next_assignee}

# ─── Events ─────────────────────────────────────────────────────────────


@app.get("/api/events")
def list_events(year: Optional[int] = None, month: Optional[int] = None):
    with db() as conn:
        if year and month:
            last_day = cal.monthrange(year, month)[1]
            start = f"{year:04d}-{month:02d}-01"
            end = f"{year:04d}-{month:02d}-{last_day:02d}"
            evs = rows(conn.execute("""
                SELECT e.*, m.name as creator_name, m.emoji as creator_emoji, m.color as creator_color
                FROM events e LEFT JOIN members m ON e.created_by=m.id
                WHERE e.event_date BETWEEN ? AND ? ORDER BY e.event_date, e.event_time
            """, (start, end)))
        else:
            evs = rows(conn.execute("""
                SELECT e.*, m.name as creator_name, m.emoji as creator_emoji, m.color as creator_color
                FROM events e LEFT JOIN members m ON e.created_by=m.id
                ORDER BY e.event_date, e.event_time
            """))
        for ev in evs:
            ev['rsvps'] = rows(conn.execute("""
                SELECT r.*, m.name, m.emoji, m.color FROM event_rsvps r
                JOIN members m ON r.member_id=m.id WHERE r.event_id=?
            """, (ev['id'],)))
        return evs


@app.post("/api/events", status_code=201)
def create_event(data: EventIn):
    with db() as conn:
        cur = conn.execute(
            "INSERT INTO events (title,description,event_date,event_time,created_by,color,location) VALUES (?,?,?,?,?,?,?)",
            (data.title,
             data.description,
             data.event_date,
             data.event_time,
             data.created_by,
             data.color,
             data.location))
        eid = cur.lastrowid
        for mid in [r['id']
                    for r in conn.execute("SELECT id FROM members").fetchall()]:
            conn.execute(
                "INSERT OR IGNORE INTO event_rsvps (event_id,member_id,status) VALUES (?,?,'pending')",
                (eid,
                 mid))
        return dict(
            conn.execute(
                "SELECT * FROM events WHERE id=?", (eid,)).fetchone())


@app.put("/api/events/{id}")
def update_event(id: int, data: EventPatch):
    with db() as conn:
        if not conn.execute(
                "SELECT 1 FROM events WHERE id=?", (id,)).fetchone():
            raise HTTPException(404)
        fields = {k: v for k, v in data.dict().items() if v is not None}
        if fields:
            conn.execute(
                f"UPDATE events SET {', '.join(f'{k}=?' for k in fields)} WHERE id=?",
                (*fields.values(), id))
        return dict(
            conn.execute(
                "SELECT * FROM events WHERE id=?", (id,)).fetchone())


@app.delete("/api/events/{id}", status_code=204)
def delete_event(id: int):
    with db() as conn:
        conn.execute("DELETE FROM events WHERE id=?", (id,))


@app.post("/api/events/{id}/rsvp")
def rsvp_event(id: int, data: RsvpIn):
    if data.status not in ('yes', 'no', 'maybe', 'pending'):
        raise HTTPException(400, "status must be yes, no, maybe, or pending")
    with db() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO event_rsvps (event_id,member_id,status) VALUES (?,?,?)",
            (id,
             data.member_id,
             data.status))
        return {
            "event_id": id,
            "member_id": data.member_id,
            "status": data.status}


@app.get("/api/stats")
def get_stats():
    with db() as conn:
        result = []
        for m in rows(conn.execute("SELECT * FROM members")):
            total_paid = conn.execute(
                "SELECT COALESCE(SUM(amount),0) as t FROM expenses WHERE paid_by=?",
                (m['id'],
                 )).fetchone()['t']
            total_split = conn.execute(
                "SELECT COALESCE(SUM(amount),0) as t FROM expense_splits WHERE member_id=?",
                (m['id'],
                 )).fetchone()['t']
            chores_done = conn.execute(
                "SELECT COUNT(*) as c FROM chore_completions WHERE member_id=?",
                (m['id'],
                 )).fetchone()['c']
            result.append({**m,
                           'total_paid': round(total_paid,
                                               2),
                           'total_split': round(total_split,
                                                2),
                           'chores_done': chores_done})
        return result

# ─── Static ─────────────────────────────────────────────────────────────


STATIC_DIR.mkdir(exist_ok=True)
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


@app.get("/{full_path:path}", include_in_schema=False)
def spa(full_path: str):
    return FileResponse(str(STATIC_DIR / "index.html"))


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app:app", host="0.0.0.0", port=8000, reload=True)

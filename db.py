import sqlite3
from datetime import datetime, timedelta

class Database:
    def __init__(self, db_name="translator_bot.db"):
        self.conn = sqlite3.connect(db_name, check_same_thread=False)
        self.create_tables()

    def create_tables(self):
        c = self.conn.cursor()
        # users table stores individual user preferences and balances
        c.execute('''CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            username TEXT,
            lang TEXT,
            balance REAL DEFAULT 0.0,
            is_premium BOOLEAN DEFAULT 0,
            premium_expiry TEXT
        )''')
        try:
            c.execute("ALTER TABLE users ADD COLUMN username TEXT")
        except sqlite3.OperationalError:
            pass

        # groups table stores chat defaults and daily rate limits
        c.execute('''CREATE TABLE IF NOT EXISTS groups (
            group_id INTEGER PRIMARY KEY,
            lang TEXT DEFAULT 'en',
            translations_today INTEGER DEFAULT 0,
            last_reset TEXT
        )''')
        
        # whitelisted groups table
        c.execute('''CREATE TABLE IF NOT EXISTS whitelisted_groups (
            group_id INTEGER PRIMARY KEY
        )''')
        
        self.conn.commit()

    def _get_today_str(self):
        return datetime.utcnow().strftime('%Y-%m-%d')

    def get_user_lang(self, user_id):
        c = self.conn.cursor()
        c.execute('SELECT lang FROM users WHERE user_id = ?', (user_id,))
        res = c.fetchone()
        return res[0] if res else None

    def get_user_lang_by_username(self, username):
        if not username: return None
        username = username.lstrip('@')
        c = self.conn.cursor()
        c.execute('SELECT lang FROM users WHERE username = ? COLLATE NOCASE', (username,))
        res = c.fetchone()
        return res[0] if res else None

    def set_user_lang(self, user_id, lang, username=None):
        c = self.conn.cursor()
        if username:
            username = username.lstrip('@')
            c.execute('INSERT OR REPLACE INTO users (user_id, lang, username, balance, is_premium, premium_expiry) VALUES (?, ?, ?, COALESCE((SELECT balance FROM users WHERE user_id = ?), 0.0), COALESCE((SELECT is_premium FROM users WHERE user_id = ?), 0), COALESCE((SELECT premium_expiry FROM users WHERE user_id = ?), NULL))', 
                      (user_id, lang, username, user_id, user_id, user_id))
        else:
            c.execute('INSERT OR REPLACE INTO users (user_id, lang, balance, is_premium, premium_expiry) VALUES (?, ?, COALESCE((SELECT balance FROM users WHERE user_id = ?), 0.0), COALESCE((SELECT is_premium FROM users WHERE user_id = ?), 0), COALESCE((SELECT premium_expiry FROM users WHERE user_id = ?), NULL))', 
                      (user_id, lang, user_id, user_id, user_id))
        self.conn.commit()

    def get_group_lang(self, group_id):
        c = self.conn.cursor()
        c.execute('SELECT lang FROM groups WHERE group_id = ?', (group_id,))
        res = c.fetchone()
        return res[0] if res else 'en'

    def set_group_lang(self, group_id, lang):
        today = self._get_today_str()
        c = self.conn.cursor()
        c.execute('INSERT OR REPLACE INTO groups (group_id, lang, translations_today, last_reset) VALUES (?, ?, COALESCE((SELECT translations_today FROM groups WHERE group_id = ?), 0), COALESCE((SELECT last_reset FROM groups WHERE group_id = ?), ?))', 
                  (group_id, lang, group_id, group_id, today))
        self.conn.commit()

    def check_and_increment_group_limit(self, group_id, daily_limit):
        """Returns True if translation is allowed. Also increments the counter."""
        today = self._get_today_str()
        c = self.conn.cursor()
        c.execute('SELECT translations_today, last_reset FROM groups WHERE group_id = ?', (group_id,))
        res = c.fetchone()

        if not res:
            # First time seeing this group
            c.execute('INSERT INTO groups (group_id, translations_today, last_reset) VALUES (?, 1, ?)', (group_id, today))
            self.conn.commit()
            return True
        
        translations_today, last_reset = res
        if last_reset != today:
            # Reset daily limit
            c.execute('UPDATE groups SET translations_today = 1, last_reset = ? WHERE group_id = ?', (today, group_id))
            self.conn.commit()
            return True
        else:
            if translations_today < daily_limit:
                c.execute('UPDATE groups SET translations_today = translations_today + 1 WHERE group_id = ?', (group_id,))
                self.conn.commit()
                return True
            return False

    def get_user_balance(self, user_id):
        c = self.conn.cursor()
        c.execute('SELECT balance, is_premium, premium_expiry FROM users WHERE user_id = ?', (user_id,))
        res = c.fetchone()
        if not res:
            return 0.0, False, None
        return res[0], bool(res[1]), res[2]

    def is_premium(self, user_id):
        c = self.conn.cursor()
        c.execute('SELECT is_premium, premium_expiry FROM users WHERE user_id = ?', (user_id,))
        res = c.fetchone()
        if res and res[0]:
            expiry = datetime.strptime(res[1], '%Y-%m-%d %H:%M:%S')
            if datetime.utcnow() < expiry:
                return True
            else:
                # Expired
                c.execute('UPDATE users SET is_premium = 0 WHERE user_id = ?', (user_id,))
                self.conn.commit()
        return False

    def deduct_balance(self, user_id, amount):
        """Returns True if sufficient balance"""
        c = self.conn.cursor()
        c.execute('SELECT balance FROM users WHERE user_id = ?', (user_id,))
        res = c.fetchone()
        if res and res[0] >= amount:
            c.execute('UPDATE users SET balance = balance - ? WHERE user_id = ?', (amount, user_id))
            self.conn.commit()
            return True
        return False

    def add_balance(self, user_id, amount):
        c = self.conn.cursor()
        c.execute('INSERT OR IGNORE INTO users (user_id) VALUES (?)', (user_id,))
        c.execute('UPDATE users SET balance = balance + ? WHERE user_id = ?', (amount, user_id))
        self.conn.commit()

    def add_premium(self, user_id, days=30):
        c = self.conn.cursor()
        c.execute('INSERT OR IGNORE INTO users (user_id) VALUES (?)', (user_id,))
        
        # Calculate new expiry
        c.execute('SELECT premium_expiry FROM users WHERE user_id = ? AND is_premium = 1', (user_id,))
        res = c.fetchone()
        
        now = datetime.utcnow()
        if res and res[0]:
            current_expiry = datetime.strptime(res[0], '%Y-%m-%d %H:%M:%S')
            if current_expiry > now:
                now = current_expiry

        new_expiry = now + timedelta(days=days)
        new_expiry_str = new_expiry.strftime('%Y-%m-%d %H:%M:%S')
        
        c.execute('UPDATE users SET is_premium = 1, premium_expiry = ? WHERE user_id = ?', (new_expiry_str, user_id))
        self.conn.commit()

    def get_stats(self):
        c = self.conn.cursor()
        c.execute('SELECT COUNT(*) FROM users')
        users_count = c.fetchone()[0]
        c.execute('SELECT COUNT(*) FROM groups')
        groups_count = c.fetchone()[0]
        c.execute('SELECT COUNT(*) FROM users WHERE is_premium = 1')
        premium_count = c.fetchone()[0]
        return users_count, groups_count, premium_count

    def add_whitelist_group(self, group_id):
        c = self.conn.cursor()
        c.execute('INSERT OR IGNORE INTO whitelisted_groups (group_id) VALUES (?)', (group_id,))
        self.conn.commit()

    def remove_whitelist_group(self, group_id):
        c = self.conn.cursor()
        c.execute('DELETE FROM whitelisted_groups WHERE group_id = ?', (group_id,))
        self.conn.commit()

    def is_group_whitelisted(self, group_id):
        c = self.conn.cursor()
        c.execute('SELECT 1 FROM whitelisted_groups WHERE group_id = ?', (group_id,))
        res = c.fetchone()
        return bool(res)

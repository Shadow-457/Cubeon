import assert from "node:assert/strict";
import { DatabaseSync } from "node:sqlite";

// Real-SQL gate: the metadata migration must be repeatable against a database
// that already carries the column (the deployed DO path), must add NO unique
// index, and duplicate usernames across accounts must coexist.
const db = new DatabaseSync(":memory:");
db.exec(`CREATE TABLE IF NOT EXISTS names (
  name TEXT PRIMARY KEY, display TEXT, secret_hash TEXT, uuid TEXT,
  uid INTEGER, blocked INTEGER DEFAULT 0, created INTEGER
)`);

function migrate() {
  const have = db.prepare("PRAGMA table_info(names)").all()
    .some((c) => c.name === "minecraft_username");
  if (!have) db.exec("ALTER TABLE names ADD COLUMN minecraft_username TEXT");
}

migrate();
migrate();
migrate();

const cols = db.prepare("PRAGMA table_info(names)").all();
const usernameCol = cols.find((c) => c.name === "minecraft_username");
assert.ok(usernameCol, "minecraft_username column exists after migration");
assert.equal(usernameCol.notnull, 0, "column is nullable");

const insert = db.prepare(
  "INSERT INTO names (name, display, secret_hash, uuid, uid, created, minecraft_username) VALUES (?, ?, ?, ?, ?, ?, ?)");
insert.run("player_11111111", "Player_11111111", "h1", "u1", 1, 1, "Twin");
insert.run("player_22222222", "Player_22222222", "h2", "u2", 2, 2, "Twin");
const twins = db.prepare(
  "SELECT name FROM names WHERE minecraft_username=?").all("Twin");
assert.equal(twins.length, 2, "duplicate usernames coexist (no uniqueness)");

insert.run("player_33333333", "Player_33333333", "h3", "u3", 3, 3, null);
const nulls = db.prepare("SELECT name FROM names WHERE minecraft_username IS NULL").all();
assert.equal(nulls.length, 1, "NULL username rows are legal");

db.prepare("UPDATE names SET minecraft_username=? WHERE name=?").run("NewName", "player_11111111");
const routing = db.prepare(
  "SELECT name, uid FROM names WHERE name=?").get("player_11111111");
assert.equal(routing.name, "player_11111111");
assert.equal(routing.uid, 1, "routing identity untouched by metadata edits");
console.log("REAL-SQL: repeatable nullable migration, no unique constraint, duplicates OK, routing immutable");
db.close();

import requests
import json
import re
from tools.git_summarizer import handle as summarize_tool

# ─── Configuration ────────────────────────────────────────────────────────────
MCP_URL    = "http://52.34.123.208:11434/api/chat"
N8N_URL    = "http://192.168.11.184:5678/webhook-test/1df1e09d-7253-440e-9b4d-11431696965a"
MODEL_NAME = "mistral-small3.1"   # Ensure this matches your local.json
# ────────────────────────────────────────────────────────────────────────────────

def fetch_commit_data():
    try:
        resp = requests.get(N8N_URL)
        resp.raise_for_status()
        return resp.json()
    except Exception as e:
        print(f"[Error] Couldn't fetch data from n8n: {e}")
        return None

def build_context(commits, diffs):
    commit_lines = [
        f"- {c['message'].strip()}  (by {c['author_name']}, {c['author_email']})"
        for c in commits
    ]
    diff_blocks = [
        f"[{d['new_path']}]\n{d['diff'].strip()}" for d in diffs
    ]
    context = (
        "You are a helpful assistant for GitLab. Use the commit and diff information below "
        "to answer questions accurately.\n\n"
        "--- COMMITS ---\n" + "\n".join(commit_lines) + "\n\n"
        "--- DIFFS ---\n" + "\n\n".join(diff_blocks) + "\n\n"
        "--- END ---"
    )
    print("\n📝 SYSTEM CONTEXT PREVIEW (first 1000 chars):\n", context[:1000])
    print(f"\n[INFO] Full context length: {len(context)} characters\n")
    return context

# Local summarization using git_summarizer tool
def local_summarize(commits, user_input):
    m = re.search(r"first\s+(\d+)", user_input.lower())
    selected = commits[:int(m.group(1))] if m else commits
    messages = [c['message'].strip() for c in selected]
    return summarize_tool("\n".join(messages))

# Local history extractor for branch queries
def local_history(commits, user_input):
    m = re.search(r"branch\s+([\w\-_/]+)", user_input.lower())
    if not m:
        return "⚠️ Couldn't parse branch name from your query."
    branch = m.group(1)
    filtered = [c for c in commits if branch in c.get('message','')]
    if not filtered:
        return f"⚠️ No commits found mentioning branch '{branch}'."
    out = [f"📜 Commits for branch '{branch}':"]
    for c in filtered:
        out.append(f"- {c['short_id']}: {c['message'].splitlines()[0]} (by {c['author_name']})")
    return "\n".join(out)

# Local extractor for last N commits

def local_last(commits, user_input):
    m = re.search(r"last\s+(\d+)", user_input.lower())
    if not m:
        return "⚠️ Couldn't parse number of commits to fetch."
    n = int(m.group(1))
    selected = commits[-n:]
    out = [f"📋 Last {n} commits:"]
    for c in selected:
        out.append(f"- {c['short_id']}: {c['message'].splitlines()[0]} (by {c['author_name']})")
    return "\n".join(out)

# Send prompt to MCP (streaming + fallback)
def ask_mcp(system_context, user_input):
    payload = {"model": MODEL_NAME, "messages": [
        {"role":"system","content":system_context},
        {"role":"user","content":user_input}
    ]}
    print("\n📤 PAYLOAD PREVIEW (1k chars):\n", json.dumps(payload, indent=2)[:1000])
    try:
        with requests.post(MCP_URL, json=payload, stream=True) as res:
            res.raise_for_status()
            print("🤖 MCP:", end=" ")
            for line in res.iter_lines():
                if not line: continue
                try:
                    chunk = json.loads(line.decode())
                    print(chunk.get('message',{}).get('content',''), end='', flush=True)
                except:
                    continue
            print("\n")
    except Exception:
        res = requests.post(MCP_URL, json=payload)
        data = res.json()
        print("🤖 MCP (fallback):", data.get('message',{}).get('content','').strip())

# Main loop
if __name__ == '__main__':
    data = fetch_commit_data()
    if not data: exit()
    commits, diffs = [], []
    if isinstance(data, list):
        for item in data:
            commits.extend(item.get('commits', []))
            diffs.extend(item.get('diffs', []))
    else:
        commits = data.get('commits', [])
        diffs    = data.get('diffs', [])
    if not commits:
        print("⚠️ No commits found.")
        exit()
    system_context = build_context(commits, diffs)
    print("✅ Commit history loaded. Ask questions or type 'exit' to quit.\n")
    while True:
        q = input("🧑 You: ").strip()
        if q.lower() in ['exit','quit']:
            print("👋 Bye!")
            break
        lq = q.lower()
        if 'summary' in lq or 'summarize' in lq:
            print(local_summarize(commits, q))
        elif 'branch' in lq:
            print(local_history(commits, q))
        elif 'last' in lq:
            print(local_last(commits, q))
        else:
            ask_mcp(system_context, q)

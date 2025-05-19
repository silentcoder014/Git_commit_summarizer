import requests
import json
import re
from datetime import datetime, date
from tools.git_summarizer import handle as summarize_tool

# ─── Configuration ────────────────────────────────────────────────────────────
MCP_URL    = "http://52.34.123.208:11434/api/chat"
N8N_URL    = "http://192.168.11.184:5678/webhook-test/1df1e09d-7253-440e-9b4d-11431696965a"
MODEL_NAME = "mistral-small3.1"
# ────────────────────────────────────────────────────────────────────────────────

def fetch_commit_data():
    """Fetch commit and diff data from n8n webhook."""
    try:
        resp = requests.get(N8N_URL, timeout=10)
        resp.raise_for_status()
        data = resp.json()
        with open("webhook_data.json", "w") as f:
            json.dump(data, f, indent=2)
        print(f"[INFO] Fetched {len(data) if isinstance(data, list) else 1} items from n8n webhook. Saved to webhook_data.json")
        return data
    except Exception as e:
        print(f"[Error] Couldn't fetch data from n8n: {e}")
        return None

def load_commit_history(data):
    """Load and sort commits and diffs from webhook data."""
    commits, diffs = [], []
    if isinstance(data, list):
        for item in data:
            # Collect commits from 'commit' and 'commits'
            if 'commit' in item and isinstance(item['commit'], dict):
                commit = item['commit']
                if commit not in commits:
                    commits.append(commit)
            if 'commits' in item and isinstance(item['commits'], list):
                for commit in item['commits']:
                    if commit not in commits:
                        commits.append(commit)
            # Collect diffs
            if 'diffs' in item and isinstance(item['diffs'], list):
                for diff in item['diffs']:
                    if diff not in diffs:
                        # Add commit date from parent item for sorting
                        diff['committed_date'] = item.get('commit', {}).get('committed_date', '')
                        diffs.append(diff)
    else:
        commits = data.get('commits', [])
        diffs = data.get('diffs', [])
        for diff in diffs:
            diff['committed_date'] = data.get('commit', {}).get('committed_date', '')
    
    # Sort commits by committed_date (newest first)
    commits.sort(key=lambda x: x.get('committed_date', ''), reverse=True)
    # Sort diffs by committed_date (newest first)
    diffs.sort(key=lambda x: x.get('committed_date', ''), reverse=True)
    
    return commits, diffs

def build_context(commits, diffs):
    """Build system context from commits and diffs."""
    commit_lines = [
        f"- {c['message'].strip()}  (by {c['author_name']}, {c['author_email']})"
        for c in commits
    ]
    diff_blocks = [
        f"[{d['new_path']}]\n{d['diff'].strip()}" for d in diffs
        if 'diff' in d and 'new_path' in d
    ]
    context = (
        "You are a helpful assistant for GitLab. Use the commit and diff information below "
        "to answer questions accurately. For 'differences' queries, provide a detailed comparison "
        "of file changes (added/removed lines) between the specified commits.\n\n"
        "--- COMMITS ---\n" + "\n".join(commit_lines) + "\n\n"
        "--- DIFFS ---\n" + "\n\n".join(diff_blocks) + "\n\n"
        "--- END ---"
    )
    print("\n📝 SYSTEM CONTEXT PREVIEW (first 1000 chars):\n", context[:1000])
    print(f"\n[INFO] Full context length: {len(context)} characters\n")
    return context

def local_summarize(commits, user_input):
    """Summarize selected commit messages."""
    m = re.search(r"first\s+(\d+)", user_input.lower())
    selected = commits[:int(m.group(1))] if m else commits
    messages = [c['message'].strip() for c in selected]
    return summarize_tool("\n".join(messages))

def local_history(commits, user_input):
    """Extract commit history for a specific branch."""
    m = re.search(r"branch\s+([\w\-_/]+)", user_input.lower())
    if not m:
        return "⚠️ Couldn't parse branch name from your query."
    branch = m.group(1)
    filtered = [c for c in commits if branch in c.get('message', '') or branch in c.get('title', '')]
    if not filtered:
        return f"⚠️ No commits found mentioning branch '{branch}'."
    out = [f"📜 Commits for branch '{branch}':"]
    for c in filtered:
        out.append(f"- {c['short_id']}: {c['message'].splitlines()[0]} (by {c['author_name']})")
    return "\n".join(out)

def local_last(commits, user_input):
    """Extract the last N commits."""
    m = re.search(r"last\s+(\d+)", user_input.lower())
    if not m:
        return "⚠️ Couldn't parse number of commits to fetch."
    n = int(m.group(1))
    if n > len(commits):
        return f"⚠️ Requested {n} commits, but only {len(commits)} available."
    selected = commits[-n:]
    out = [f"📋 Last {n} commits:"]
    for c in selected:
        out.append(f"- {c['short_id']}: {c['message'].splitlines()[0]} (by {c['author_name']})")
    return "\n".join(out)

def local_today(commits, user_input):
    """Extract commits from today."""
    today = date.today()  # May 16, 2025
    filtered = []
    for c in commits:
        for date_field in ['committed_date', 'created_at', 'authored_date']:
            if date_field in c:
                try:
                    commit_date = datetime.strptime(c[date_field], '%Y-%m-%dT%H:%M:%S.%f%z').date()
                    if commit_date == today:
                        filtered.append(c)
                        break
                except ValueError:
                    continue
    if not filtered:
        return f"⚠️ No commits found for today ({today})."
    out = [f"📅 Commits for today ({today}):"]
    for c in filtered:
        out.append(f"- {c['short_id']}: {c['message'].splitlines()[0]} (by {c['author_name']})")
    return "\n".join(out)

def local_differences(commits, diffs, user_input):
    """Extract and format differences between the last two commits in kivicare_develop."""
    branch = "kivicare_develop"
    # Filter commits related to kivicare_develop
    branch_commits = [
        c for c in commits
        if branch in c.get('message', '') or branch in c.get('title', '')
    ]
    if len(branch_commits) < 2:
        return f"⚠️ Not enough commits found for branch '{branch}' to compare."
    
    # Get the last two commits (newest first)
    commit_1, commit_2 = branch_commits[0], branch_commits[1]
    
    # Try to find diffs associated with commit dates
    commit_1_diffs, commit_2_diffs = [], []
    commit_1_date = commit_1.get('committed_date', '')
    commit_2_date = commit_2.get('committed_date', '')
    for d in diffs:
        diff_date = d.get('committed_date', '')
        if diff_date == commit_1_date:
            commit_1_diffs.append(d)
        elif diff_date == commit_2_date:
            commit_2_diffs.append(d)
    
    # Fallback: Use recent diffs if no date match
    if not commit_1_diffs and not commit_2_diffs:
        commit_1_diffs = diffs[:10]  # Most recent diffs
        commit_2_diffs = diffs[10:20] if len(diffs) > 10 else []
    
    # Format differences
    out = [f"📊 Differences between last two commits in '{branch}':"]
    out.append(f"Commit 1: {commit_1['short_id']} - {commit_1['message'].splitlines()[0]} (by {commit_1['author_name']})")
    out.append(f"Commit 2: {commit_2['short_id']} - {commit_2['message'].splitlines()[0]} (by {commit_2['author_name']})")
    out.append("\nFile Changes:")
    
    # Combine and show unique diffs
    seen_paths = set()
    for diff in commit_1_diffs + commit_2_diffs:
        if 'new_path' in diff and 'diff' in diff and diff['new_path'] not in seen_paths:
            out.append(f"\n[{diff['new_path']}]")
            out.append(diff['diff'].strip())
            seen_paths.add(diff['new_path'])
    
    # Summarize the diffs
    diff_text = "\n".join([d['diff'] for d in commit_1_diffs + commit_2_diffs if 'diff' in d])
    if diff_text:
        out.append("\n📝 Diff Summary:")
        out.append(summarize_tool(diff_text))
    
    return "\n".join(out)

def ask_mcp(system_context, user_input):
    """Send query to MCP server with streaming support."""
    payload = {
        "model": MODEL_NAME,
        "messages": [
            {"role": "system", "content": system_context},
            {"role": "user", "content": user_input}
        ],
        "temperature": 0.15,
        "stream": True
    }
    print("\n📤 PAYLOAD PREVIEW (1k chars):\n", json.dumps(payload, indent=2)[:1000])
    try:
        with requests.post(MCP_URL, json=payload, stream=True, timeout=30) as res:
            res.raise_for_status()
            print("🤖 MCP:", end=" ")
            response_text = ""
            for line in res.iter_lines():
                if not line:
                    continue
                try:
                    chunk = json.loads(line.decode())
                    content = chunk.get('message', {}).get('content', '')
                    print(content, end='', flush=True)
                    response_text += content
                except Exception as e:
                    print(f"[Warning] Error parsing chunk: {e}")
                    continue
            print("\n")
            return response_text
    except Exception as e:
        print(f"[Error] MCP request failed: {e}")
        try:
            res = requests.post(MCP_URL, json=payload, timeout=30)
            res.raise_for_status()
            data = res.json()
            content = data.get('message', {}).get('content', '').strip()
            print("🤖 MCP (fallback):", content)
            return content
        except Exception as e:
            print(f"[Error] MCP fallback failed: {e}")
            return "⚠️ Unable to get response from MCP server."

# Main loop
if __name__ == '__main__':
    data = fetch_commit_data()
    if not data:
        print("⚠️ Exiting due to fetch failure.")
        exit(1)
    
    commits, diffs = load_commit_history(data)
    
    if not commits:
        print("⚠️ No commits found.")
        exit(1)
    
    print(f"[INFO] Loaded {len(commits)} commits and {len(diffs)} diffs")
    system_context = build_context(commits, diffs)
    print("✅ Commit history loaded. Ask questions or type 'exit' to quit.\n")
    
    while True:
        q = input("🧑 You: ").strip()
        if q.lower() in ['exit', 'quit']:
            print("👋 Bye!")
            break
        lq = q.lower()
        if 'summary' in lq or 'summarize' in lq:
            print(local_summarize(commits, q))
        elif 'branch' in lq:
            print(local_history(commits, q))
        elif 'last' in lq:
            print(local_last(commits, q))
        elif 'today' in lq:
            print(local_today(commits, q))
        elif 'difference' in lq or 'diff' in lq:
            print(local_differences(commits, diffs, q))
        else:
            print(ask_mcp(system_context, q))

# import requests
# import json
# import re
# from datetime import datetime, date
# from tools.git_summarizer import handle as summarize_tool

# # ─── Configuration ────────────────────────────────────────────────────────────
# MCP_URL    = "http://52.34.123.208:11434/api/chat"
# N8N_URL    = "http://192.168.11.184:5678/webhook-test/1df1e09d-7253-440e-9b4d-11431696965a"
# MODEL_NAME = "mistral-small3.1"  # Adjust if server supports a different model
# # ────────────────────────────────────────────────────────────────────────────────

# def fetch_commit_data():
#     """Fetch commit and diff data from n8n webhook."""
#     try:
#         resp = requests.get(N8N_URL, timeout=10)
#         resp.raise_for_status()
#         data = resp.json()
#         with open("webhook_data.json", "w") as f:
#             json.dump(data, f, indent=2)
#         print(f"[INFO] Fetched {len(data) if isinstance(data, list) else 1} items from n8n webhook. Saved to webhook_data.json")
#         return data
#     except Exception as e:
#         print(f"[Error] Couldn't fetch data from n8n: {e}")
#         return None

# def load_commit_history(data):
#     """Load commits and diffs from webhook data using a for-loop."""
#     commits, diffs = [], []
#     if isinstance(data, list):
#         for item in data:
#             if 'commits' in item:
#                 for commit in item['commits']:
#                     if commit not in commits:  # Avoid duplicates
#                         commits.append(commit)
#             if 'diffs' in item:
#                 for diff in item['diffs']:
#                     if diff not in diffs:
#                         diffs.append(diff)
#     else:
#         commits = data.get('commits', [])
#         diffs = data.get('diffs', [])
#     return commits, diffs

# def build_context(commits, diffs):
#     """Build system context from commits and diffs."""
#     commit_lines = [
#         f"- {c['message'].strip()}  (by {c['author_name']}, {c['author_email']})"
#         for c in commits
#     ]
#     diff_blocks = [
#         f"[{d['new_path']}]\n{d['diff'].strip()}" for d in diffs
#         if 'diff' in d and 'new_path' in d
#     ]
#     context = (
#         "You are a helpful assistant for GitLab. Use the commit and diff information below "
#         "to answer questions accurately. For 'differences' queries, provide a detailed comparison "
#         "of file changes (added/removed lines) between the specified commits.\n\n"
#         "--- COMMITS ---\n" + "\n".join(commit_lines) + "\n\n"
#         "--- DIFFS ---\n" + "\n\n".join(diff_blocks) + "\n\n"
#         "--- END ---"
#     )
#     print("\n📝 SYSTEM CONTEXT PREVIEW (first 1000 chars):\n", context[:1000])
#     print(f"\n[INFO] Full context length: {len(context)} characters\n")
#     return context

# def local_summarize(commits, user_input):
#     """Summarize selected commit messages."""
#     m = re.search(r"first\s+(\d+)", user_input.lower())
#     selected = commits[:int(m.group(1))] if m else commits
#     messages = [c['message'].strip() for c in selected]
#     return summarize_tool("\n".join(messages))

# def local_history(commits, user_input):
#     """Extract commit history for a specific branch."""
#     m = re.search(r"branch\s+([\w\-_/]+)", user_input.lower())
#     if not m:
#         return "⚠️ Couldn't parse branch name from your query."
#     branch = m.group(1)
#     filtered = [c for c in commits if branch in c.get('message', '') or branch in c.get('title', '')]
#     if not filtered:
#         return f"⚠️ No commits found mentioning branch '{branch}'."
#     out = [f"📜 Commits for branch '{branch}':"]
#     for c in filtered:
#         out.append(f"- {c['short_id']}: {c['message'].splitlines()[0]} (by {c['author_name']})")
#     return "\n".join(out)

# def local_last(commits, user_input):
#     """Extract the last N commits."""
#     m = re.search(r"last\s+(\d+)", user_input.lower())
#     if not m:
#         return "⚠️ Couldn't parse number of commits to fetch."
#     n = int(m.group(1))
#     if n > len(commits):
#         return f"⚠️ Requested {n} commits, but only {len(commits)} available."
#     selected = commits[-n:]
#     out = [f"📋 Last {n} commits:"]
#     for c in selected:
#         out.append(f"- {c['short_id']}: {c['message'].splitlines()[0]} (by {c['author_name']})")
#     return "\n".join(out)

# def local_today(commits, user_input):
#     """Extract commits from today."""
#     today = date.today()  # May 16, 2025
#     filtered = []
#     for c in commits:
#         if 'committed_date' in c:
#             try:
#                 commit_date = datetime.strptime(c['committed_date'], '%Y-%m-%dT%H:%M:%S.%f%z').date()
#                 if commit_date == today:
#                     filtered.append(c)
#             except ValueError:
#                 continue
#         elif 'created_at' in c:
#             try:
#                 commit_date = datetime.strptime(c['created_at'], '%Y-%m-%dT%H:%M:%S.%f%z').date()
#                 if commit_date == today:
#                     filtered.append(c)
#             except ValueError:
#                 continue
#     if not filtered:
#         return f"⚠️ No commits found for today ({today})."
#     out = [f"📅 Commits for today ({today}):"]
#     for c in filtered:
#         out.append(f"- {c['short_id']}: {c['message'].splitlines()[0]} (by {c['author_name']})")
#     return "\n".join(out)

# def local_differences(commits, diffs, user_input):
#     """Extract and format differences between the last two commits in kivicare_develop."""
#     branch = "kivicare_develop"
#     # Filter commits related to kivicare_develop
#     branch_commits = []
#     for c in commits:
#         if branch in c.get('message', '') or branch in c.get('title', ''):
#             branch_commits.append(c)
#     if len(branch_commits) < 2:
#         return f"⚠️ Not enough commits found for branch '{branch}' to compare."
    
#     # Get the last two commits (most recent first)
#     branch_commits.sort(key=lambda x: x.get('committed_date', ''), reverse=True)
#     commit_1, commit_2 = branch_commits[0], branch_commits[1]
    
#     # Try to find diffs associated with these commits
#     commit_1_diffs, commit_2_diffs = [], []
#     for d in diffs:
#         if 'commit_id' in d and 'id' in commit_1 and d['commit_id'] == commit_1['id']:
#             commit_1_diffs.append(d)
#         elif 'commit_id' in d and 'id' in commit_2 and d['commit_id'] == commit_2['id']:
#             commit_2_diffs.append(d)
    
#     # Fallback: Use recent diffs sorted by commit date proximity
#     if not commit_1_diffs and not commit_2_diffs:
#         sorted_diffs = sorted(diffs, key=lambda x: x.get('committed_date', ''), reverse=True)
#         commit_1_diffs = sorted_diffs[:10]  # Most recent diffs
#         commit_2_diffs = sorted_diffs[10:20] if len(sorted_diffs) > 10 else []
    
#     # Format differences
#     out = [f"📊 Differences between last two commits in '{branch}':"]
#     out.append(f"Commit 1: {commit_1['short_id']} - {commit_1['message'].splitlines()[0]} (by {commit_1['author_name']})")
#     out.append(f"Commit 2: {commit_2['short_id']} - {commit_2['message'].splitlines()[0]} (by {commit_2['author_name']})")
#     out.append("\nFile Changes:")
    
#     # Combine and show unique diffs
#     seen_paths = set()
#     for diff in commit_1_diffs + commit_2_diffs:
#         if 'new_path' in diff and 'diff' in diff and diff['new_path'] not in seen_paths:
#             out.append(f"\n[{diff['new_path']}]")
#             out.append(diff['diff'].strip())
#             seen_paths.add(diff['new_path'])
    
#     # Summarize the diffs
#     diff_text = "\n".join([d['diff'] for d in commit_1_diffs + commit_2_diffs if 'diff' in d])
#     if diff_text:
#         out.append("\n📝 Diff Summary:")
#         out.append(summarize_tool(diff_text))
    
#     return "\n".join(out)

# def ask_mcp(system_context, user_input):
#     """Send query to MCP server with streaming support."""
#     payload = {
#         "model": MODEL_NAME,
#         "messages": [
#             {"role": "system", "content": system_context},
#             {"role": "user", "content": user_input}
#         ]
#     }
#     print("\n📤 PAYLOAD PREVIEW (1k chars):\n", json.dumps(payload, indent=2)[:1000])
#     try:
#         with requests.post(MCP_URL, json=payload, stream=True, timeout=30) as res:
#             res.raise_for_status()
#             print("🤖 MCP:", end=" ")
#             response_text = ""
#             for line in res.iter_lines():
#                 if not line:
#                     continue
#                 try:
#                     chunk = json.loads(line.decode())
#                     content = chunk.get('message', {}).get('content', '')
#                     print(content, end='', flush=True)
#                     response_text += content
#                 except Exception as e:
#                     print(f"[Warning] Error parsing chunk: {e}")
#                     continue
#             print("\n")
#             return response_text
#     except Exception as e:
#         print(f"[Error] MCP request failed: {e}")
#         try:
#             res = requests.post(MCP_URL, json=payload, timeout=30)
#             res.raise_for_status()
#             data = res.json()
#             content = data.get('message', {}).get('content', '').strip()
#             print("🤖 MCP (fallback):", content)
#             return content
#         except Exception as e:
#             print(f"[Error] MCP fallback failed: {e}")
#             return "⚠️ Unable to get response from MCP server."

# # Main loop
# if __name__ == '__main__':
#     data = fetch_commit_data()
#     if not data:
#         print("⚠️ Exiting due to fetch failure.")
#         exit(1)
    
#     commits, diffs = load_commit_history(data)
    
#     if not commits:
#         print("⚠️ No commits found.")
#         exit(1)
    
#     print(f"[INFO] Loaded {len(commits)} commits and {len(diffs)} diffs")
#     system_context = build_context(commits, diffs)
#     print("✅ Commit history loaded. Ask questions or type 'exit' to quit.\n")
    
#     while True:
#         q = input("🧑 You: ").strip()
#         if q.lower() in ['exit', 'quit']:
#             print("👋 Bye!")
#             break
#         lq = q.lower()
#         if 'summary' in lq or 'summarize' in lq:
#             print(local_summarize(commits, q))
#         elif 'branch' in lq:
#             print(local_history(commits, q))
#         elif 'last' in lq:
#             print(local_last(commits, q))
#         elif 'today' in lq:
#             print(local_today(commits, q))
#         elif 'difference' in lq or 'diff' in lq:
#             print(local_differences(commits, diffs, q))
#         else:
#             print(ask_mcp(system_context, q))
# import requests
# import json
# import re
# from datetime import datetime, date
# from tools.git_summarizer import handle as summarize_tool

# # ─── Configuration ────────────────────────────────────────────────────────────
# MCP_URL    = "http://52.34.123.208:11434/api/chat"
# N8N_URL    = "http://192.168.11.184:5678/webhook-test/1df1e09d-7253-440e-9b4d-11431696965a"
# MODEL_NAME = "mistral-small3.1"  # Adjust if server supports a different model
# # ────────────────────────────────────────────────────────────────────────────────

# def fetch_commit_data():
#     """Fetch commit and diff data from n8n webhook."""
#     try:
#         resp = requests.get(N8N_URL, timeout=15)
#         resp.raise_for_status()
#         data = resp.json()
#         with open("webhook_data.json", "w") as f:
#             json.dump(data, f, indent=2)
#         print(f"[INFO] Fetched {len(data)} items from n8n webhook. Saved to webhook_data.json")
#         return data
#     except Exception as e:
#         print(f"[Error] Couldn't fetch data from n8n: {e}")
#         return None

# def build_context(commits, diffs):
#     """Build system context from commits and diffs."""
#     commit_lines = [
#         f"- {c['message'].strip()}  (by {c['author_name']}, {c['author_email']})"
#         for c in commits
#     ]
#     diff_blocks = [
#         f"[{d['new_path']}]\n{d['diff'].strip()}" for d in diffs
#         if 'diff' in d and 'new_path' in d
#     ]
#     context = (
#         "You are a helpful assistant for GitLab. Use the commit and diff information below "
#         "to answer questions accurately. For 'differences' queries, provide a detailed comparison "
#         "of file changes (added/removed lines) between the specified commits.\n\n"
#         "--- COMMITS ---\n" + "\n".join(commit_lines) + "\n\n"
#         "--- DIFFS ---\n" + "\n\n".join(diff_blocks) + "\n\n"
#         "--- END ---"
#     )
#     print("\n📝 SYSTEM CONTEXT PREVIEW (first 1000 chars):\n", context[:1000])
#     print(f"\n[INFO] Full context length: {len(context)} characters\n")
#     return context

# def local_summarize(commits, user_input):
#     """Summarize selected commit messages."""
#     m = re.search(r"first\s+(\d+)", user_input.lower())
#     selected = commits[:int(m.group(1))] if m else commits
#     messages = [c['message'].strip() for c in selected]
#     return summarize_tool("\n".join(messages))

# def local_history(commits, user_input):
#     """Extract commit history for a specific branch."""
#     m = re.search(r"branch\s+([\w\-_/]+)", user_input.lower())
#     if not m:
#         return "⚠️ Couldn't parse branch name from your query."
#     branch = m.group(1)
#     filtered = [c for c in commits if branch in c.get('message', '') or branch in c.get('title', '')]
#     if not filtered:
#         return f"⚠️ No commits found mentioning branch '{branch}'."
#     out = [f"📜 Commits for branch '{branch}':"]
#     for c in filtered:
#         out.append(f"- {c['short_id']}: {c['message'].splitlines()[0]} (by {c['author_name']})")
#     return "\n".join(out)

# def local_last(commits, user_input):
#     """Extract the last N commits."""
#     m = re.search(r"last\s+(\d+)", user_input.lower())
#     if not m:
#         return "⚠️ Couldn't parse number of commits to fetch."
#     n = int(m.group(1))
#     if n > len(commits):
#         return f"⚠️ Requested {n} commits, but only {len(commits)} available."
#     selected = commits[-n:]
#     out = [f"📋 Last {n} commits:"]
#     for c in selected:
#         out.append(f"- {c['short_id']}: {c['message'].splitlines()[0]} (by {c['author_name']})")
#     return "\n".join(out)

# def local_today(commits, user_input):
#     """Extract commits from today."""
#     today = date.today()  # May 16, 2025
#     filtered = [
#         c for c in commits
#         if 'committed_date' in c and
#         datetime.strptime(c['committed_date'], '%Y-%m-%dT%H:%M:%S.%f%z').date() == today
#     ]
#     if not filtered:
#         return f"⚠️ No commits found for today ({today})."
#     out = [f"📅 Commits for today ({today}):"]
#     for c in filtered:
#         out.append(f"- {c['short_id']}: {c['message'].splitlines()[0]} (by {c['author_name']})")
#     return "\n".join(out)

# def local_differences(commits, diffs, user_input):
#     """Extract and format differences between the last two commits in kivicare_develop."""
#     branch = "kivicare_develop"
#     # Filter commits related to kivicare_develop
#     branch_commits = [c for c in commits if branch in c.get('message', '') or branch in c.get('title', '')]
#     if len(branch_commits) < 2:
#         return f"⚠️ Not enough commits found for branch '{branch}' to compare."
    
#     # Get the last two commits
#     commit_1, commit_2 = branch_commits[-1], branch_commits[-2]
    
#     # Try to find diffs associated with these commits
#     commit_1_diffs = [d for d in diffs if d.get('commit_id') == commit_1.get('id')] if commit_1.get('id') else []
#     commit_2_diffs = [d for d in diffs if d.get('commit_id') == commit_2.get('id')] if commit_2.get('id') else []
    
#     # Fallback: Use all diffs if commit_id is missing
#     if not commit_1_diffs and not commit_2_diffs:
#         commit_1_diffs = diffs[-10:]  # Use recent diffs as fallback
#         commit_2_diffs = diffs[-20:-10] if len(diffs) > 20 else []
    
#     # Format differences
#     out = [f"📊 Differences between last two commits in '{branch}':"]
#     out.append(f"Commit 1: {commit_1['short_id']} - {commit_1['message'].splitlines()[0]} (by {commit_1['author_name']})")
#     out.append(f"Commit 2: {commit_2['short_id']} - {commit_2['message'].splitlines()[0]} (by {commit_2['author_name']})")
#     out.append("\nFile Changes:")
    
#     # Combine and show diffs
#     seen_paths = set()
#     for diff in commit_1_diffs + commit_2_diffs:
#         if 'new_path' in diff and 'diff' in diff and diff['new_path'] not in seen_paths:
#             out.append(f"\n[{diff['new_path']}]")
#             out.append(diff['diff'].strip())
#             seen_paths.add(diff['new_path'])
    
#     # Summarize the diffs
#     diff_text = "\n".join([d['diff'] for d in commit_1_diffs + commit_2_diffs if 'diff' in d])
#     if diff_text:
#         out.append("\n📝 Diff Summary:")
#         out.append(summarize_tool(diff_text))
    
#     return "\n".join(out)

# def ask_mcp(system_context, user_input):
#     """Send query to MCP server with streaming support."""
#     payload = {
#         "model": MODEL_NAME,
#         "messages": [
#             {"role": "system", "content": system_context},
#             {"role": "user", "content": user_input}
#         ]
#     }
#     print("\n📤 PAYLOAD PREVIEW (1k chars):\n", json.dumps(payload, indent=2)[:1000])
#     try:
#         with requests.post(MCP_URL, json=payload, stream=True, timeout=30) as res:
#             res.raise_for_status()
#             print("🤖 MCP:", end=" ")
#             response_text = ""
#             for line in res.iter_lines():
#                 if not line:
#                     continue
#                 try:
#                     chunk = json.loads(line.decode())
#                     content = chunk.get('message', {}).get('content', '')
#                     print(content, end='', flush=True)
#                     response_text += content
#                 except Exception as e:
#                     print(f"[Warning] Error parsing chunk: {e}")
#                     continue
#             print("\n")
#             return response_text
#     except Exception as e:
#         print(f"[Error] MCP request failed: {e}")
#         # Fallback to non-streaming request
#         try:
#             res = requests.post(MCP_URL, json=payload, timeout=30)
#             res.raise_for_status()
#             data = res.json()
#             content = data.get('message', {}).get('content', '').strip()
#             print("🤖 MCP (fallback):", content)
#             return content
#         except Exception as e:
#             print(f"[Error] MCP fallback failed: {e}")
#             return "⚠️ Unable to get response from MCP server."

# # Main loop
# if __name__ == '__main__':
#     data = fetch_commit_data()
#     if not data:
#         print("⚠️ Exiting due to fetch failure.")
#         exit(1)
    
#     commits, diffs = [], []
#     if isinstance(data, list):
#         for item in data:
#             commits.extend(item.get('commits', []))
#             diffs.extend(item.get('diffs', []))
#     else:
#         commits = data.get('commits', [])
#         diffs = data.get('diffs', [])
    
#     if not commits:
#         print("⚠️ No commits found.")
#         exit(1)
    
#     print(f"[INFO] Loaded {len(commits)} commits and {len(diffs)} diffs")
#     system_context = build_context(commits, diffs)
#     print("✅ Commit history loaded. Ask questions or type 'exit' to quit.\n")
    
#     while True:
#         q = input("🧑 You: ").strip()
#         if q.lower() in ['exit', 'quit']:
#             print("👋 Bye!")
#             break
#         lq = q.lower()
#         if 'summary' in lq or 'summarize' in lq:
#             print(local_summarize(commits, q))
#         elif 'branch' in lq:
#             print(local_history(commits, q))
#         elif 'last' in lq:
#             print(local_last(commits, q))
#         elif 'today' in lq:
#             print(local_today(commits, q))
#         elif 'difference' in lq or 'diff' in lq:
#             print(local_differences(commits, diffs, q))
#         else:
#             print(ask_mcp(system_context, q))
# import requests
# import json
# import re
# from tools.git_summarizer import handle as summarize_tool

# # ─── Configuration ────────────────────────────────────────────────────────────
# MCP_URL    = "http://52.34.123.208:11434/api/chat"
# N8N_URL    = "http://192.168.11.184:5678/webhook-test/1df1e09d-7253-440e-9b4d-11431696965a"
# MODEL_NAME = "mistral-small3.1"  # Updated to a more capable model (e.g., mistral or a local alternative)
# # ────────────────────────────────────────────────────────────────────────────────

# def fetch_commit_data():
#     """Fetch commit and diff data from n8n webhook."""
#     try:
#         resp = requests.get(N8N_URL, timeout=10)
#         resp.raise_for_status()
#         data = resp.json()
#         print(f"[INFO] Fetched {len(data)} items from n8n webhook")
#         return data
#     except Exception as e:
#         print(f"[Error] Couldn't fetch data from n8n: {e}")
#         return None

# def build_context(commits, diffs):
#     """Build system context from commits and diffs."""
#     commit_lines = [
#         f"- {c['message'].strip()}  (by {c['author_name']}, {c['author_email']})"
#         for c in commits
#     ]
#     diff_blocks = [
#         f"[{d['new_path']}]\n{d['diff'].strip()}" for d in diffs
#         if 'diff' in d and 'new_path' in d
#     ]
#     context = (
#         "You are a helpful assistant for GitLab. Use the commit and diff information below "
#         "to answer questions accurately. For 'differences' queries, provide a detailed comparison "
#         "of file changes (added/removed lines) between the specified commits.\n\n"
#         "--- COMMITS ---\n" + "\n".join(commit_lines) + "\n\n"
#         "--- DIFFS ---\n" + "\n\n".join(diff_blocks) + "\n\n"
#         "--- END ---"
#     )
#     print("\n📝 SYSTEM CONTEXT PREVIEW (first 1000 chars):\n", context[:1000])
#     print(f"\n[INFO] Full context length: {len(context)} characters\n")
#     return context

# def local_summarize(commits, user_input):
#     """Summarize selected commit messages."""
#     m = re.search(r"first\s+(\d+)", user_input.lower())
#     selected = commits[:int(m.group(1))] if m else commits
#     messages = [c['message'].strip() for c in selected]
#     return summarize_tool("\n".join(messages))

# def local_history(commits, user_input):
#     """Extract commit history for a specific branch."""
#     m = re.search(r"branch\s+([\w\-_/]+)", user_input.lower())
#     if not m:
#         return "⚠️ Couldn't parse branch name from your query."
#     branch = m.group(1)
#     filtered = [c for c in commits if branch in c.get('message', '') or branch in c.get('title', '')]
#     if not filtered:
#         return f"⚠️ No commits found mentioning branch '{branch}'."
#     out = [f"📜 Commits for branch '{branch}':"]
#     for c in filtered:
#         out.append(f"- {c['short_id']}: {c['message'].splitlines()[0]} (by {c['author_name']})")
#     return "\n".join(out)

# def local_last(commits, user_input):
#     """Extract the last N commits."""
#     m = re.search(r"last\s+(\d+)", user_input.lower())
#     if not m:
#         return "⚠️ Couldn't parse number of commits to fetch."
#     n = int(m.group(1))
#     if n > len(commits):
#         return f"⚠️ Requested {n} commits, but only {len(commits)} available."
#     selected = commits[-n:]
#     out = [f"📋 Last {n} commits:"]
#     for c in selected:
#         out.append(f"- {c['short_id']}: {c['message'].splitlines()[0]} (by {c['author_name']})")
#     return "\n".join(out)

# def local_differences(commits, diffs, user_input):
#     """Extract and format differences between the last two commits in kivicare_develop."""
#     branch = "kivicare_develop"
#     # Filter commits related to kivicare_develop
#     branch_commits = [c for c in commits if branch in c.get('message', '') or branch in c.get('title', '')]
#     if len(branch_commits) < 2:
#         return f"⚠️ Not enough commits found for branch '{branch}' to compare."
    
#     # Get the last two commits
#     commit_1, commit_2 = branch_commits[-1], branch_commits[-2]
    
#     # Find diffs associated with these commits (assuming webhook provides commit IDs)
#     commit_1_diffs = [d for d in diffs if d.get('commit_id') == commit_1.get('id')]
#     commit_2_diffs = [d for d in diffs if d.get('commit_id') == commit_2.get('id')]
    
#     # Format differences
#     out = [f"📊 Differences between last two commits in '{branch}':"]
#     out.append(f"Commit 1: {commit_1['short_id']} - {commit_1['message'].splitlines()[0]} (by {commit_1['author_name']})")
#     out.append(f"Commit 2: {commit_2['short_id']} - {commit_2['message'].splitlines()[0]} (by {commit_2['author_name']})")
#     out.append("\nFile Changes:")
    
#     # Combine and compare diffs
#     for diff in commit_1_diffs + commit_2_diffs:
#         if 'new_path' in diff and 'diff' in diff:
#             out.append(f"\n[{diff['new_path']}]")
#             out.append(diff['diff'].strip())
    
#     # Summarize the diffs using the summarizer tool
#     diff_text = "\n".join([d['diff'] for d in commit_1_diffs + commit_2_diffs if 'diff' in d])
#     if diff_text:
#         out.append("\n📝 Diff Summary:")
#         out.append(summarize_tool(diff_text))
    
#     return "\n".join(out)

# def ask_mcp(system_context, user_input):
#     """Send query to MCP server with streaming support."""
#     payload = {
#         "model": MODEL_NAME,
#         "messages": [
#             {"role": "system", "content": system_context},
#             {"role": "user", "content": user_input}
#         ]
#     }
#     print("\n📤 PAYLOAD PREVIEW (1k chars):\n", json.dumps(payload, indent=2)[:1000])
#     try:
#         with requests.post(MCP_URL, json=payload, stream=True, timeout=15) as res:
#             res.raise_for_status()
#             print("🤖 MCP:", end=" ")
#             response_text = ""
#             for line in res.iter_lines():
#                 if not line:
#                     continue
#                 try:
#                     chunk = json.loads(line.decode())
#                     content = chunk.get('message', {}).get('content', '')
#                     print(content, end='', flush=True)
#                     response_text += content
#                 except Exception as e:
#                     print(f"[Warning] Error parsing chunk: {e}")
#                     continue
#             print("\n")
#             return response_text
#     except Exception as e:
#         print(f"[Error] MCP request failed: {e}")
#         # Fallback to non-streaming request
#         try:
#             res = requests.post(MCP_URL, json=payload, timeout=15)
#             res.raise_for_status()
#             data = res.json()
#             content = data.get('message', {}).get('content', '').strip()
#             print("🤖 MCP (fallback):", content)
#             return content
#         except Exception as e:
#             print(f"[Error] MCP fallback failed: {e}")
#             return "⚠️ Unable to get response from MCP server."

# # Main loop
# if __name__ == '__main__':
#     data = fetch_commit_data()
#     if not data:
#         print("⚠️ Exiting due to fetch failure.")
#         exit(1)
    
#     commits, diffs = [], []
#     if isinstance(data, list):
#         for item in data:
#             commits.extend(item.get('commits', []))
#             diffs.extend(item.get('diffs', []))
#     else:
#         commits = data.get('commits', [])
#         diffs = data.get('diffs', [])
    
#     if not commits:
#         print("⚠️ No commits found.")
#         exit(1)
    
#     print(f"[INFO] Loaded {len(commits)} commits and {len(diffs)} diffs")
#     system_context = build_context(commits, diffs)
#     print("✅ Commit history loaded. Ask questions or type 'exit' to quit.\n")
    
#     while True:
#         q = input("🧑 You: ").strip()
#         if q.lower() in ['exit', 'quit']:
#             print("👋 Bye!")
#             break
#         lq = q.lower()
#         if 'summary' in lq or 'summarize' in lq:
#             print(local_summarize(commits, q))
#         elif 'branch' in lq:
#             print(local_history(commits, q))
#         elif 'last' in lq:
#             print(local_last(commits, q))
#         elif 'difference' in lq or 'diff' in lq:
#             print(local_differences(commits, diffs, q))
#         else:
#             ask_mcp(system_context, q)
# import requests
# import json
# import re
# from tools.git_summarizer import handle as summarize_tool

# # ─── Configuration ────────────────────────────────────────────────────────────
# MCP_URL    = "http://52.34.123.208:11434/api/chat"
# N8N_URL    = "http://192.168.11.184:5678/webhook-test/1df1e09d-7253-440e-9b4d-11431696965a"
# MODEL_NAME = "mistral-small3.1"   # Ensure this matches your local.json
# # ────────────────────────────────────────────────────────────────────────────────

# def fetch_commit_data():
#     try:
#         resp = requests.get(N8N_URL)
#         resp.raise_for_status()
#         return resp.json()
#     except Exception as e:
#         print(f"[Error] Couldn't fetch data from n8n: {e}")
#         return None

# def build_context(commits, diffs):
#     commit_lines = [
#         f"- {c['message'].strip()}  (by {c['author_name']}, {c['author_email']})"
#         for c in commits
#     ]
#     diff_blocks = [
#         f"[{d['new_path']}]\n{d['diff'].strip()}" for d in diffs
#     ]
#     context = (
#         "You are a helpful assistant for GitLab. Use the commit and diff information below "
#         "to answer questions accurately.\n\n"
#         "--- COMMITS ---\n" + "\n".join(commit_lines) + "\n\n"
#         "--- DIFFS ---\n" + "\n\n".join(diff_blocks) + "\n\n"
#         "--- END ---"
#     )
#     print("\n📝 SYSTEM CONTEXT PREVIEW (first 1000 chars):\n", context[:1000])
#     print(f"\n[INFO] Full context length: {len(context)} characters\n")
#     return context

# # Local summarization using git_summarizer tool
# def local_summarize(commits, user_input):
#     m = re.search(r"first\s+(\d+)", user_input.lower())
#     selected = commits[:int(m.group(1))] if m else commits
#     messages = [c['message'].strip() for c in selected]
#     return summarize_tool("\n".join(messages))

# # Local history extractor for branch queries
# def local_history(commits, user_input):
#     m = re.search(r"branch\s+([\w\-_/]+)", user_input.lower())
#     if not m:
#         return "⚠️ Couldn't parse branch name from your query."
#     branch = m.group(1)
#     filtered = [c for c in commits if branch in c.get('message','')]
#     if not filtered:
#         return f"⚠️ No commits found mentioning branch '{branch}'."
#     out = [f"📜 Commits for branch '{branch}':"]
#     for c in filtered:
#         out.append(f"- {c['short_id']}: {c['message'].splitlines()[0]} (by {c['author_name']})")
#     return "\n".join(out)

# # Local extractor for last N commits

# def local_last(commits, user_input):
#     m = re.search(r"last\s+(\d+)", user_input.lower())
#     if not m:
#         return "⚠️ Couldn't parse number of commits to fetch."
#     n = int(m.group(1))
#     selected = commits[-n:]
#     out = [f"📋 Last {n} commits:"]
#     for c in selected:
#         out.append(f"- {c['short_id']}: {c['message'].splitlines()[0]} (by {c['author_name']})")
#     return "\n".join(out)

# # Send prompt to MCP (streaming + fallback)
# def ask_mcp(system_context, user_input):
#     payload = {"model": MODEL_NAME, "messages": [
#         {"role":"system","content":system_context},
#         {"role":"user","content":user_input}
#     ]}
#     print("\n📤 PAYLOAD PREVIEW (1k chars):\n", json.dumps(payload, indent=2)[:1000])
#     try:
#         with requests.post(MCP_URL, json=payload, stream=True) as res:
#             res.raise_for_status()
#             print("🤖 MCP:", end=" ")
#             for line in res.iter_lines():
#                 if not line: continue
#                 try:
#                     chunk = json.loads(line.decode())
#                     print(chunk.get('message',{}).get('content',''), end='', flush=True)
#                 except:
#                     continue
#             print("\n")
#     except Exception:
#         res = requests.post(MCP_URL, json=payload)
#         data = res.json()
#         print("🤖 MCP (fallback):", data.get('message',{}).get('content','').strip())

# # Main loop
# if __name__ == '__main__':
#     data = fetch_commit_data()
#     if not data: exit()
#     commits, diffs = [], []
#     if isinstance(data, list):
#         for item in data:
#             commits.extend(item.get('commits', []))
#             diffs.extend(item.get('diffs', []))
#     else:
#         commits = data.get('commits', [])
#         diffs    = data.get('diffs', [])
#     if not commits:
#         print("⚠️ No commits found.")
#         exit()
#     system_context = build_context(commits, diffs)
#     print("✅ Commit history loaded. Ask questions or type 'exit' to quit.\n")
#     while True:
#         q = input("🧑 You: ").strip()
#         if q.lower() in ['exit','quit']:
#             print("👋 Bye!")
#             break
#         lq = q.lower()
#         if 'summary' in lq or 'summarize' in lq:
#             print(local_summarize(commits, q))
#         elif 'branch' in lq:
#             print(local_history(commits, q))
#         elif 'last' in lq:
#             print(local_last(commits, q))
#         else:
#             ask_mcp(system_context, q)

def handle(input_data):
    """
    Summarize Git commit logs passed as a string
    """
    commits = input_data.strip().split("\n")
    summary = f"📦 Total Commits: {len(commits)}\n\n"

    for commit in commits:
        summary += f"- {commit.strip()}\n"

    return summary


# def main(input):
#     commits = input.get("commits", [])
#     diffs = input.get("diffs", [])

#     summary = []

#     for c in commits:
#         author = c.get("author_name", "unknown")
#         message = c.get("message", "").strip()
#         summary.append(f"- {author}: {message}")

#     diff_summary = []
#     for d in diffs:
#         file = d.get("new_path", "unknown file")
#         diff_text = d.get("diff", "")
#         trimmed = diff_text[:300].replace("\n", " ")  # Limit and clean
#         diff_summary.append(f"* {file}: {trimmed}...")

#     return (
#         "Here is a summary of the commit history:\n\n"
#         + "\n".join(summary)
#         + "\n\nChanges:\n"
#         + "\n".join(diff_summary)
#     )

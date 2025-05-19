from transformers import pipeline
import re

def handle(input_data):
    """
    Summarize Git commit logs or diff text passed as a string.
    Returns a concise summary of changes.
    """
    if not input_data.strip():
        return "⚠️ No data provided for summarization."
    
    # Initialize a summarizer (using BART for better results)
    try:
        summarizer = pipeline("summarization", model="facebook/bart-large-cnn")
    except Exception as e:
        print(f"[Warning] Could not load summarizer model: {e}. Falling back to basic summary.")
        # Basic summary if model fails
        lines = input_data.strip().split("\n")
        commit_count = len([line for line in lines if line.startswith("-") or not line.startswith(("[", "@@"))])
        return f"📦 Total Commits or Changes: {commit_count}\n\nSummary: {len(lines)} lines of changes detected."

    # Clean and split input into manageable chunks
    max_length = 1024  # BART's max token length
    chunks = [input_data[i:i+max_length] for i in range(0, len(input_data), max_length)]
    
    summaries = []
    for chunk in chunks:
        # Remove excessive whitespace and normalize
        cleaned_chunk = re.sub(r"\s+", " ", chunk.strip())
        if not cleaned_chunk:
            continue
        try:
            summary = summarizer(cleaned_chunk, max_length=150, min_length=30, do_sample=False)
            summaries.append(summary[0]["summary_text"])
        except Exception as e:
            print(f"[Warning] Error summarizing chunk: {e}")
            summaries.append("Partial summary: Changes detected but could not be summarized.")
    
    if not summaries:
        return "⚠️ Unable to generate summary."
    
    return f"📦 Total Commits or Changes: {len(chunks)}\n\nSummary:\n" + "\n".join(summaries)
# def handle(input_data):
#     """
#     Summarize Git commit logs passed as a string
#     """
#     commits = input_data.strip().split("\n")
#     summary = f"📦 Total Commits: {len(commits)}\n\n"

#     for commit in commits:
#         summary += f"- {commit.strip()}\n"

#     return summary


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

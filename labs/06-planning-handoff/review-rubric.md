# Manual review rubric

Give only the handoff file to a reader who did not write it. Do not provide
chat history or explain the plan verbally.

Score one point for each question the reader can answer from the file:

1. What milestone is active, and which evidence IDs passed, failed, or did not
   run?
2. What is the single next action?
3. What observable condition prevents further progress?
4. What rollback action protects existing data?
5. What information or human decision is still missing?

A score of 5/5 passes the handoff test. A lower score means the handoff must be
revised even if `verify.py` passes. Record the reader's answers and the
resulting revision; do not silently explain missing context.

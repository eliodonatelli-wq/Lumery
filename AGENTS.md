# Lumerys project rules

These rules apply to work throughout this project.

1. Git is the primary system for versioning the code.
2. Do not automatically create backups, ZIP archives, project copies, or alternate
   files with suffixes such as `_backup`, `_old`, `_v2`, or similar names.
3. Before significant changes, check that the Git working tree is clean. If there
   are uncommitted changes, report them to the user before proceeding.
4. Before risky work, propose a safety commit instead of duplicating files.
5. Do not create commits or push automatically without the user's authorization.
6. Do not delete existing backups without the user's consent.
7. Never include astronomical images, temporary data, caches, or large files in
   the repository. Keep these outside version control and respect `.gitignore`.
8. Keep documentation, code comments, and technical names in English.
9. Do not change application behavior to enforce these rules. These are rules
   for development work; leave existing runtime behavior unchanged unless the
   user explicitly authorizes a separate application change.

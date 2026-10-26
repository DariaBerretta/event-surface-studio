# Publish to your GitHub account

This is a separate project and should be published in a **new** repository, not inside `MoveEnet_OFK`.

## Easy path: create the repository, then upload the project

1. Open <https://github.com/new> while signed in.
2. Repository name: `event-surface-studio`.
3. Choose **Private** (recommended initially). You can make it public later.
4. Do **not** initialize with a README, license, or .gitignore (all already included here).
5. Click **Create repository**.
6. Send the resulting repository URL to ChatGPT, which can add the files using the connected GitHub integration.

## Alternative: publish via Git from your Linux computer

After creating the empty repository above, open a terminal in the extracted project directory:

```bash
cd event-surface-studio
git init -b main
git add .
git commit -m "Initial Event Surface Studio GUI"
git remote add origin https://github.com/DariaBerretta/event-surface-studio.git
git push -u origin main
```

GitHub will request authentication if you use HTTPS. If you already use an SSH key, substitute the SSH remote URL.

If GitHub CLI (`gh`) is installed and authenticated, you can instead create and push in one command (starting in the directory with the project):

```bash
git init -b main
git add .
git commit -m "Initial Event Surface Studio GUI"
gh repo create event-surface-studio --private --source=. --remote=origin --push
```

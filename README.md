# Minted Inventory Log — team web app

Deploy this **small folder** to get a public URL. Your teammates open the link,
upload Shopify’s inventory CSV, and download the branded Excel count workbook.
Nothing is stored on the server after each visit.

## One-time: put this on GitHub

1. Create a new empty repository on GitHub (any name, e.g. `minted-inventory-log`).
2. Open Terminal in **this folder** (`inventory-log-cloud`) and run (use your repo URL):

   ```bash
   git init -b main
   git add .
   git commit -m "Initial inventory log app"
   git remote add origin https://github.com/YOUR_USER/minted-inventory-log.git
   git push -u origin main
   ```

If you don’t use Terminal, use **GitHub Desktop**: File → Add Local Repository → choose this folder → Publish.

## Deploy on Streamlit Community Cloud (free)

1. Sign in at https://share.streamlit.io with your GitHub account.
2. **New app** → pick the repo you just pushed.
3. Branch: `main`
4. Main file path: `app.py`
5. Advanced → Python version can stay default (or 3.11 if offered); `runtime.txt` pins 3.11.
6. **Deploy**. In ~2 minutes you get a URL like `https://minted-inventory-log.streamlit.app`.

Share that URL with the team. **Only this repo** goes to GitHub—not your whole Dropbox/Minted folder.

## When you change the Excel logic

After editing `build_inventory_log.py` (or `app.py`) in Dropbox, copy the updated files into this folder again (replace the two `.py` files), then commit and push:

```bash
cp "/path/to/Minted/build_inventory_log.py" .
cp "/path/to/Minted/app.py" .
git add -A && git commit -m "Update builder" && git push
```

Streamlit Cloud rebuilds the app automatically on push.

## Local test

```bash
pip install -r requirements.txt
streamlit run app.py
```

# Laburnum Newsletter Reader Deployment

This site is a static newsletter reader. It can be deployed to any static host.

## Files to publish

- `index.html`
- `404.html`
- `newsletter_search.html`
- `laburnum_enews_this_year.json`
- `_headers`
- `.nojekyll`

## Recommended host

Cloudflare Pages is the best fit for this project:

- static site support
- easy custom domain support
- automatic HTTPS
- simple Git-based deploys
- preview deployments for changes

## Cloudflare Pages setup

1. Create a GitHub repository and put these files in the repository root.
2. Push the repository to GitHub on the `main` branch.
3. In Cloudflare Pages, create a new Pages project from that GitHub repository.
4. Use:
   - Production branch: `main`
   - Build command: `exit 0`
   - Build output directory: `/`
5. Deploy.
6. Optional: attach a custom domain such as a school or community subdomain.

## GitHub Pages setup

1. Create a GitHub repository and put these files in the repository root.
2. Push to the `main` branch.
3. In GitHub repository settings, enable GitHub Pages.
4. Set the publishing source to deploy from the `main` branch root.
5. Wait for the site to publish.

## Refreshing newsletter data

Before a new deploy, refresh the JSON archive:

```powershell
python fetch_laburnum_enews.py --refresh
```

Then commit the updated `laburnum_enews_this_year.json` and redeploy.

## Notes

- The site currently reads image URLs directly from the school newsletter source.
- If you want the public site to be fully self-contained, the next step is to download and serve those images locally.

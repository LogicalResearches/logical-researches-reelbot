# Logical Researches ReelBot

This is a working, zero-cost research-to-Instagram-Reel pipeline built for
[`@logical_researches`](https://www.instagram.com/logical_researches/).

It can:

1. read recent stories from a whitelist of institutional RSS feeds;
2. rank them for recency, relevance, visual potential and safety;
3. extract the original article instead of copying an aggregator;
4. write a five-part script grounded only in that article;
5. reject numbers or claim evidence that cannot be matched to the source;
6. collect compatible public-domain or Creative Commons visuals from Wikimedia Commons;
7. generate narration, burned-in subtitles, a cover and a vertical MP4;
8. create a public review page; and
9. publish the reviewed Reel through Meta's official API.

The safe default is **generate and review**. Once you have tested a few drafts, one repository
variable turns on automatic daily posting.

## What stays free

| Facility | Free service used | Key required? |
|---|---|---:|
| Story discovery | NASA, ESA and MIT RSS feeds | No |
| Script and natural voice | Gemini API free tier | Yes, free |
| Backup voice | FFmpeg `flite`, fully offline | No |
| Visuals | Wikimedia Commons CC/public-domain media | No |
| Editing, subtitles and music bed | Pillow + FFmpeg | No |
| Daily scheduler | GitHub Actions in a public repository | No paid plan |
| Public temporary video URL | GitHub Pages | No paid plan |
| Instagram publishing | Meta Instagram API | Yes, free token |

Expected operating cost: **₹0 within the services' free quotas**. Free-plan rules can change,
so the workflow deliberately posts only one Reel per day. Do not add billing details to Gemini
if you want a strict zero-spend setup.

## One-time setup

### 1. Put this project on GitHub

1. Create a free GitHub account if needed.
2. Create a **public** repository named `logical-researches-reelbot`.
3. Upload the complete contents of this folder to the repository root.
4. Open **Settings → Pages → Build and deployment** and select **GitHub Actions**.

Public repositories use standard GitHub-hosted Actions runners without paid minutes. Do not put
tokens in a file or commit them; the workflow reads them only from encrypted repository secrets.

### 2. Create the free Gemini key

1. Open [Google AI Studio — API keys](https://aistudio.google.com/app/apikey).
2. Create a key in a project without billing.
3. In the GitHub repository, open **Settings → Secrets and variables → Actions → Secrets**.
4. Add a repository secret named `GEMINI_API_KEY`.

The free tier may use submitted content to improve Google products. ReelBot sends only text from
already-public institutional articles, not private files.

### 3. Prepare Instagram for official publishing

Meta does not allow official API publishing to an ordinary personal Instagram account.

1. In Instagram, change `@logical_researches` to a free **Creator** account.
2. Create or connect a Facebook Page to that account.
3. Create a free app at [Meta for Developers](https://developers.facebook.com/apps/).
4. Add the **Instagram API / Instagram Graph API** product.
5. Use the Facebook Login route and grant:
   `instagram_basic`, `instagram_content_publish`, and `pages_read_engagement`.
   `pages_show_list` is useful while locating the connected Page.
6. Generate a long-lived access token for the account that controls the Page.
7. Find the Instagram professional account ID from the Page's
   `instagram_business_account.id` field.

Meta also supports the newer Instagram Login permissions
`instagram_business_basic` and `instagram_business_content_publish`. The publishing code works
with either route because both use the same container-and-publish pattern.

Add these two encrypted GitHub repository secrets:

| Secret name | Value |
|---|---|
| `INSTAGRAM_USER_ID` | The numeric Instagram professional account ID |
| `INSTAGRAM_ACCESS_TOKEN` | The valid long-lived access token |

Relevant official documentation:

- [Instagram content publishing](https://developers.facebook.com/docs/instagram-platform/content-publishing/)
- [Instagram container reference](https://developers.facebook.com/docs/instagram-platform/instagram-graph-api/reference/ig-container/)
- [Graph API v25.0 changelog](https://developers.facebook.com/docs/graph-api/changelog/version25.0/)

Never send the token in chat, email or a screenshot. If it is exposed, invalidate it in Meta and
create a replacement.

### 4. Generate the first review Reel

1. Open the repository's **Actions** tab.
2. Select **Logical Researches ReelBot**.
3. Choose **Run workflow**.
4. Select `generate-only` and leave `topic_url` blank.
5. When it finishes, open the GitHub Pages link shown for the deployment.

The page contains the MP4, exact caption and source link. The Actions run also keeps a downloadable
review copy for seven days.

To force a specific story, rerun `generate-only` and paste the original institutional article URL
into `topic_url`.

### 5. Publish the reviewed draft

Run the workflow again with `publish-current`. It posts the exact MP4 and caption already visible
on the review page; it does not regenerate them.

For a one-off fully automatic test, choose `generate-and-post`.

### 6. Enable the daily automation

After two or three successful reviewed posts:

1. Open **Settings → Secrets and variables → Actions → Variables**.
2. Add `REELBOT_SCHEDULE_MODE` with the value `auto`.

The scheduled workflow runs daily at **6:00 PM India time**. Set the variable to `review` or delete
it at any time to return to review mode. Change the cron line in
`.github/workflows/reelbot.yml` if a different time is needed.

## Run it locally

Python 3.11+ and FFmpeg are required.

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[dev]'
python -m reelbot demo --output demo_output
```

The offline demo needs no API key or internet connection. Open `demo_output/index.html` to review
the sample. The fallback voice is intentionally basic; the configured Gemini voice is used when a
free key is present.

For a real draft:

```bash
export GEMINI_API_KEY='your-key'
python -m reelbot generate --output site --work-dir work
```

Check the installation without printing secrets:

```bash
python -m reelbot doctor
python -m reelbot doctor --online
```

The online check reads the account username/type from Meta and confirms that the token and user ID
work. It never prints the token.

## Customize the page

Edit `config.yaml` to change:

- the niche, CTA and preferred keywords;
- approved RSS feeds and domains;
- duration and word-count range;
- Gemini models/voice;
- colors, fonts and typography; or
- Graph API version.

Keep new sources institutional or primary. A high-view headline is not worth posting if its source
cannot support the claim.

## Built-in guardrails

- Only approved source domains enter automatic selection.
- Previously used URLs are stored in the deployed `history.json`.
- Script numbers must occur in the source text.
- Each generated claim carries internal evidence in `draft.json`.
- Source URL and visual credits are added to the caption.
- Licensed music is not scraped; the renderer makes a small original procedural sound bed.
- Tokens are read from environment variables/GitHub Secrets only.
- The default scheduled mode never posts without review.

No automated fact checker is perfect. Before switching to `auto`, review several drafts and remove
any feed category that repeatedly produces weak or overly technical stories.

## Tests

```bash
python -m pytest
python -m reelbot demo --output demo_output
python -m reelbot validate demo_output/reels/*.mp4
```

The test suite checks source-number grounding, safe domains, the Meta container flow and utility
functions. The demo performs an end-to-end 1080×1920 H.264/AAC render.

## Common setup errors

| Error | Fix |
|---|---|
| `Missing INSTAGRAM_USER_ID` | Add the exact GitHub Actions secret name |
| Meta error about permissions | Reissue the token with content-publishing permissions |
| Account is `PERSONAL` | Convert it to Creator or Business |
| Meta cannot fetch the video | Confirm GitHub Pages is enabled and the MP4 URL opens publicly |
| `GEMINI_API_KEY is not set` | Add the key; rendering still falls back to offline voice/script |
| Token suddenly stops working | Generate a fresh long-lived Meta token and replace the secret |
| Pages deployment is rejected | Set Pages build source to **GitHub Actions** |

## License

The ReelBot code is MIT licensed. Each downloaded Wikimedia visual keeps its own license and credit,
which is recorded in `draft.json` and added to the post caption.

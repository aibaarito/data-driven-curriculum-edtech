# README research: what award-winning hackathon projects show first

Prepared 12 November 2026 to restructure this repository's [README](../README.md). It records which projects were
studied, the evidence that each one won an award, what their READMEs do well or poorly, and which patterns were
adopted here and why.

**Scope and caveats**

* This research does not claim that a README caused any project to win. Judges score demos, pitches and code. The
  aim is to describe presentation patterns found in projects that did win, and to decide which suit this product.
* Award evidence comes from organizers or official channels where possible: Google blogs and competition pages,
  the official Google for Developers account, university news offices and Stanford's student newspaper. A repository
  calling itself a winner was not accepted as evidence on its own.
* **Access limitation.** Organizer websites (Devpost, blog.google, developers.googleblog.com, ai.google.dev) could
  not be fetched from this environment. Award facts were confirmed from search-engine results that index those
  official pages, and the links below point to the pages themselves. README contents were read directly from GitHub
  on 12 November 2026. Each table row says which link was checked how.

## 1. Projects studied

| # | Project | Competition, year | Award (type) | Award evidence | Repository / README |
|---|---|---|---|---|---|
| 1 | **HeadHome**: dementia wandering aid | Google Solution Challenge 2023 | One of the **Winning 3** (top tier, three equal winners) | [Google Keyword blog: top three 2023 teams](https://blog.google/technology/developers/google-student-developer-clubs-solution-challenge-2023/); [NTU Renaissance Engineering achievements page](https://www.ntu.edu.sg/honours-college/admissions/undergraduate/premier-scholar-programmes/renaissance-engineering-programme/achievements/year-2023/google-solution-challenge-2023) | [GSC23-HeadHome/HeadHome](https://github.com/GSC23-HeadHome/HeadHome) · [README](https://github.com/GSC23-HeadHome/HeadHome/blob/main/README.md) |
| 2 | **ATTI**: memory notes for people with mild dementia | Google Solution Challenge 2024 | One of the **Winning 3** | [Google for Developers on X, Demo Day results](https://x.com/googledevs/status/1807942266411008142); [Asia Business Daily](https://www.asiae.co.kr/en/article/2024071015432358252) | [H0ngJu/atti](https://github.com/H0ngJu/atti) · [README](https://github.com/H0ngJu/atti/blob/main/README.md) |
| 3 | **Gaze Link**: eye-gesture communication for people with ALS | Gemini API Developer Competition 2024 | **Best Android App** (category award, not Best Overall) | [Android Developers Blog](https://android-developers.googleblog.com/2024/11/gaze-link-wins-best-android-app-gemini-api-developer-competition.html); [competition project page](https://ai.google.dev/competition/projects/gaze-link); [winners announcement](https://developers.googleblog.com/en/announcing-the-winners-of-the-gemini-api-developer-competition/) | [Jonassunhk/Gaze-Link](https://github.com/Jonassunhk/Gaze-Link) · [README](https://github.com/Jonassunhk/Gaze-Link/blob/main/README.md). The repository was matched by name and description; the competition page could not be opened to confirm that it links to this repository. |
| 4 | **ShipSense.ai**: overfishing detection and data dashboard | TreeHacks (Stanford) 2023 | **Grand Prize, Sustainability track** plus a sponsor award (Meta Best Innovation). This is a track grand prize, not the overall grand prize. | [Devpost project page](https://devpost.com/software/shipsense-ai-novel-data-augmentation-protocol), confirmed through the search index | [SohamGovande/treehacks-2023](https://github.com/SohamGovande/treehacks-2023) · [README](https://github.com/SohamGovande/treehacks-2023/blob/main/README.md) |
| 5 | **HiveMind**: AI-assisted check of student understanding in virtual lessons | TreeHacks 2025 | **Grand Prize in Education** (track prize, Zoom-sponsored) | [NIU College of Business news](https://cob.news.niu.edu/2025/05/14/mis-student-samarth-shiramshetty-wins-grand-prize-in-education-at-stanford-universitys-treehacks/); [Stanford Daily prize coverage](https://stanforddaily.com/2025/02/18/treehacks-awards-200000-in-prizes-to-students-from-around-the-world/) | [AahilAliCodes/HiveMind](https://github.com/AahilAliCodes/HiveMind) (README: title and event name only). **Repository association unconfirmed:** found by name and event; the award sources do not link it. Used only as a contrast example. |

**Checked and excluded from the winner set**

| Candidate | Why excluded |
|---|---|
| ViddyScribe, Best Web App, Gemini API Developer Competition 2024 ([Chrome for Developers blog](https://developer.chrome.com/blog/video-accessibility-gemini-competition)) | The award is confirmed, but the matching repository [thesumedh/ViddyScribe](https://github.com/thesumedh/ViddyScribe) describes a later app "drawing inspiration from award-winning accessibility solutions". It is not demonstrably the winning code. |
| `hackmit2021-jgft`, described as "HackMIT 2021 Education Track Winner" | The only evidence is the repository's own description. No organizer source was found. |
| engagED, TreeHacks 2025 education project | Built for the event, but no prize evidence was found. The TreeHacks 2025 Education prize went to HiveMind. |
| `Tzur01/Outdraw` | Same name as the 2024 Most Creative App winner, Outdraw AI, but the repository was created in 2026 and does not identify itself as that entry. |

The set is smaller than the 6–8 projects originally planned. Several winners in education and data analytics had no
public repository, or none could be linked to the award, so they were not included.

## 2. How each README presents the project

| Dimension | HeadHome | ATTI | Gaze Link | ShipSense.ai | HiveMind |
|---|---|---|---|---|---|
| First screen | Logo, name, tagline, then a large product image | Banner image, name, one-paragraph problem statement, video links | Long academic title, one-paragraph description | Three headline achievements, then a screenshot | Title and event name only |
| Problem and user | Dedicated *Problem Statement*; three user groups (patient, caregiver, volunteer) | Long *Overview* and *Necessity* with interviews and user tests | One paragraph naming users and disability | Clear *TL;DR* with problem, data gap and result | None |
| Demo | Video thumbnail linking to YouTube | Two YouTube links | YouTube channel and user manual | One screenshot | None |
| Features | One section per user group, plus a feature graphic | Screens in grid tables, grouped by feature | None in the README | Prose ("What we're shipping") | None |
| Architecture | Cloud architecture image with layered explanation | Skills table of logos | None | Prose description of team split | None |
| Setup | *Getting Started* exists but is short | Step-by-step *How To Run* near the top, including demo accounts | None | None | None |
| Evidence and testing | Monitoring and Looker dashboard screenshots | User-test results | Testing claims appear on the competition page, not in the README | Accuracy claim (96%), no method link | None |
| Limitations | Not stated | Not stated | Not stated | "What we learned" admits narrowed scope | None |
| Visual restraint | Heavy: 9 logo icons, SDG graphics | Very heavy: dozens of phone screenshots, KakaoTalk file names as alt text | Minimal | Moderate | Minimal |
| Image accessibility | Mostly meaningful alt text | Generic alt text ("Untitled4", "image") | No images | Generic alt text ("image") | No images |
| Time-pressed judge | Good: problem, demo and features within one scroll | Mixed: setup comes before the product explanation | Weak: no visual, no feature list | Good: the TL;DR answers "what and why" in six bullets | Unusable |

## 3. Patterns to adopt and patterns to avoid

**Adopt**

1. **Answer "what is it, for whom" on the first screen.** HeadHome's tagline and image, and ShipSense's TL;DR, do this
   within a few lines. Gaze Link's academic title delays it.
2. **Put one real screenshot of the product near the top.** Every README a judge could understand quickly had one
   (HeadHome, ShipSense). The weakest examples (Gaze Link, HiveMind) had none.
3. **Organise features around the user's job or question.** HeadHome groups features by user role; ATTI by feature
   area. Both read better than a technology list.
4. **Give a short TL;DR of the core claim and its evidence.** ShipSense lists the problem, the gap and the result as
   bullets before the narrative.
5. **Show the architecture as one compact diagram with a short explanation.** HeadHome pairs its cloud diagram with a
   paragraph per layer.
6. **Keep run instructions copy-pasteable.** ATTI's numbered steps and environment-file example are easy to follow.

**Avoid**

1. **Walls of logos and decorative graphics** (HeadHome's icon row, ATTI's SDG and logo images). They add length but
   no evidence.
2. **Dozens of screenshots with meaningless alt text** (ATTI's `KakaoTalk_…`, ShipSense's `image`). They are hard to
   scan and inaccessible to screen-reader users.
3. **Unqualified performance numbers** (ShipSense's 96% accuracy with no method or dataset link). This product's
   value is careful statistics, so any number must state its scope.
4. **"Coming soon" sections and placeholder READMEs** (the excluded JGFT repository, HiveMind).
5. **Leaving limitations unstated.** None of the five READMEs had a limitations section. For an analytics tool that
   advises educators, honest limitations are part of credibility.
6. **Setup before purpose.** ATTI's *How To Run* appears before the reader knows what the app does.

## 4. How the findings shaped this repository's README

| Pattern | Applied as | Reason |
|---|---|---|
| First-screen clarity (HeadHome, ShipSense) | Name, one-sentence purpose, intended users, Russian-interface and synthetic-data notes, navigation links, then the Decision Center screenshot | A judge sees the product and its audience without scrolling far |
| TL;DR of claims (ShipSense) | "The four questions it answers" table: question → screen → what the app computes | Maps directly onto the four official challenge requirements |
| Features by user job (HeadHome, ATTI) | Workflow section ordered as the user moves: import → analyse → compare → plan → explain → export, each with input, output, decision supported and limitation | Explains observable behaviour instead of adjectives |
| Compact architecture (HeadHome) | One Mermaid diagram showing real request paths, with the optional Gemini path drawn dashed | GitHub renders Mermaid from text, so it stays accurate and accessible without an image |
| Restrained visuals (avoiding HeadHome/ATTI excess) | Three screenshots in total, each showing a different capability, with descriptive alt text; three badges, each verifiable | Meets the request for "a little more graphics" without decoration |
| Copy-pasteable setup (ATTI) | Short quick start in the README; full instructions, ports and safety warnings preserved in [SETUP.md](SETUP.md) | Developers get a working path without losing hard-won operational detail |
| Honest limitations (a gap in every example) | Dedicated *Limitations* section plus scope labels on every quoted statistic | Matches the product's emphasis on evidence quality and on association rather than causation |
| Evidence of implementation (partly HeadHome) | *Verification* section with fresh test counts, commands and links to the detailed records | Gives judges checkable evidence instead of claims |

Not adopted: demo video links (no published video exists), a public demo button (no verified public URL exists),
SDG graphics, contributor photo grids and a license badge (no license has been selected).

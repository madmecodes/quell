# Quell — All Links

## Submission (the ones judges use)
| What | Link |
|------|------|
| Quell console (hosted project URL) | https://quell-dashboard-908906947513.us-central1.run.app |
| ShopWave demo store (the monitored app) | https://shopwave-908906947513.us-central1.run.app |
| Public source repo (MIT license) | https://github.com/madmecodes/quell |
| Demo video | (record + paste YouTube/Vimeo link here) |
| Devpost submission | (paste your Devpost project URL here) |

## Repo documents
| What | Link |
|------|------|
| README | https://github.com/madmecodes/quell/blob/master/README.md |
| Architecture + diagrams | https://github.com/madmecodes/quell/blob/master/ARCHITECTURE.md |
| Demo script | https://github.com/madmecodes/quell/blob/master/DEMO.md |
| Video shot-list | https://github.com/madmecodes/quell/blob/master/VIDEO.md |
| Devpost write-up (draft) | https://github.com/madmecodes/quell/blob/master/DEVPOST.md |
| Deploy guide | https://github.com/madmecodes/quell/blob/master/DEPLOY.md |

## Live API endpoints (console)
| What | Link |
|------|------|
| Pipeline state | https://quell-dashboard-908906947513.us-central1.run.app/api/state |
| Live Dynatrace metrics | https://quell-dashboard-908906947513.us-central1.run.app/api/metrics |
| Autonomous monitor status | https://quell-dashboard-908906947513.us-central1.run.app/api/monitor |
| Cumulative impact | https://quell-dashboard-908906947513.us-central1.run.app/api/impact |
| ShopWave chaos/fault state | https://shopwave-908906947513.us-central1.run.app/api/chaos |

## Infrastructure (private — your reference, not for submission)
| What | Where |
|------|-------|
| Dynatrace tenant (Grail) | https://xqs90163.apps.dynatrace.com |
| GCP project | sentinel-hack-2026 |
| GCP account | buildshift.org@gmail.com |
| Cloud Run region | us-central1 |
| Cloud Run services | quell-dashboard, shopwave |
| Slack alerts | #incidents in "Madme's Space" workspace |
| GitHub account | madmecodes |

## Quick demo flow
1. Open the **store** -> Operations -> inject any of the 5 fault scenarios.
2. Open the **console** -> Quell auto-detects within ~15s (no button), diagnoses live, shows charts + topology + DQL.
3. Approve the rollback -> a prevented-incident alert posts to Slack #incidents.
4. Approve the learning -> the agent improves (4 -> 2 tool calls).
5. Clear the fault on the store -> console returns to "watching".

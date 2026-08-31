# Architecture decision records

Why this project is built the way it is. Read 0001 and 0003 first; the rest
assume them.

| # | Decision |
| --- | --- |
| [0001](0001-reverse-engineer-voyager-instead-of-a-browser.md) | Reverse engineer the Voyager API instead of driving a browser |
| [0002](0002-use-dash-finders-not-graphql.md) | Use the dash REST finders, not `profileView` and not GraphQL |
| [0003](0003-manage-cookies-by-hand-and-persist-the-session.md) | Manage cookies by hand and persist the rotated session |
| [0004](0004-throttle-requests-to-limit-account-risk.md) | Throttle requests to limit account risk |
| [0005](0005-response-schema-and-per-section-failure-isolation.md) | Own the response schema, and isolate section failures |
| [0006](0006-fastapi-uv-and-both-http-verbs.md) | FastAPI, uv, and keeping both GET and POST |
| [0007](0007-the-caller-brings-the-cookies.md) | The caller brings the cookies; the server stores nothing |

0007 supersedes part of 0003 and part of 0006. Both are left as written, with
a pointer at the top, because the reasoning that led to them still holds for
the situation they were written in.

Format is [Michael Nygard's](https://cognitect.com/blog/2011/11/15/documenting-architecture-decisions):
status, context, decision, consequences.

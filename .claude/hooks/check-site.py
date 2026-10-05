#!/usr/bin/env python3
# 홈페이지 점검: Claude가 작업을 마칠 때(Stop 훅) 자동으로 실행돼요.
# index.html에서 아래 세 가지를 찾아요.
#   1) 깨진 내부 링크: href="#이름"인데 id="이름"인 곳이 없음
#   2) 없는 사진 파일: <img>/<source>의 src·srcset에 적힌 파일이 저장소에 없음
#   3) 사진 설명 빠짐: <img>에 alt가 없거나 비어 있음
# 문제가 있으면 Claude에게 고치라고 돌려보내요(한 번만). 그래도 남아 있으면 사용자에게 경고만 보여 줘요.
# 직접 실행: python3 .claude/hooks/check-site.py [점검할 html 파일]
import json
import os
import sys
from html.parser import HTMLParser
from urllib.parse import unquote, urlsplit


class SiteParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.ids = set()
        self.links = []   # (줄 번호, 주소)
        self.images = []  # (줄 번호, 파일 경로)
        self.no_alt = []  # (줄 번호, src)

    def handle_starttag(self, tag, attrs):
        line = self.getpos()[0]
        a = dict(attrs)
        if a.get("id"):
            self.ids.add(a["id"])
        if tag == "a" and a.get("name"):
            self.ids.add(a["name"])
        href = a.get("href")
        if href is not None and href.startswith("#"):
            self.links.append((line, href))
        if tag in ("img", "source"):
            paths = []
            if a.get("src"):
                paths.append(a["src"])
            for part in (a.get("srcset") or "").split(","):
                part = part.strip()
                if part:
                    paths.append(part.split()[0])
            for p in paths:
                self.images.append((line, p))
        if tag == "img":
            alt = a.get("alt")
            if alt is None or not alt.strip():
                self.no_alt.append((line, a.get("src", "(src 없음)")))

    handle_startendtag = handle_starttag


def check(html_path):
    base = os.path.dirname(os.path.abspath(html_path))
    p = SiteParser()
    with open(html_path, encoding="utf-8") as f:
        p.feed(f.read())

    problems = []
    for line, href in p.links:
        target = unquote(href[1:])
        if not target:
            problems.append(f"{line}번째 줄: 깨진 내부 링크 href=\"#\" (이동할 곳이 없음)")
        elif target not in p.ids:
            problems.append(f"{line}번째 줄: 깨진 내부 링크 href=\"{href}\" (id=\"{target}\"인 곳이 없음)")

    seen = set()
    for line, src in p.images:
        u = urlsplit(src)
        if u.scheme or src.startswith("//"):  # 외부 주소, data: 는 건너뜀
            continue
        path = os.path.normpath(os.path.join(base, unquote(u.path)))
        if not os.path.isfile(path) and (line, src) not in seen:
            seen.add((line, src))
            problems.append(f"{line}번째 줄: 없는 사진 파일 \"{src}\"")

    for line, src in p.no_alt:
        problems.append(f"{line}번째 줄: 사진 설명(alt)이 없거나 비어 있음 \"{src}\"")
    return problems


def main():
    # 직접 실행할 때는 파일 경로를 받고, 훅으로 실행될 때는 표준 입력의 JSON을 읽어요.
    if len(sys.argv) > 1:
        problems = check(sys.argv[1])
        print("\n".join(problems) if problems else "문제 없음")
        sys.exit(1 if problems else 0)

    try:
        data = json.load(sys.stdin)
    except Exception:
        data = {}
    root = os.environ.get("CLAUDE_PROJECT_DIR") or data.get("cwd") or os.getcwd()
    html_path = os.path.join(root, "index.html")
    if not os.path.isfile(html_path):
        sys.exit(0)

    problems = check(html_path)
    if not problems:
        sys.exit(0)

    listing = "\n".join("- " + x for x in problems)
    if data.get("stop_hook_active"):
        # 이미 한 번 돌려보냈는데도 남은 문제: 무한 반복을 막으려고 멈추게 두고 경고만 보여 줘요.
        print(json.dumps({"systemMessage": "홈페이지 점검: 아직 남은 문제가 있어요.\n" + listing},
                         ensure_ascii=False))
        sys.exit(0)

    reason = (
        "홈페이지 자동 점검(index.html)에서 문제를 찾았어요.\n" + listing + "\n\n"
        "고칠 수 있는 것은 CLAUDE.md 규칙대로 고쳐 주세요(깨진 링크는 맞는 id로, alt는 사진 내용을 설명하는 한국어로). "
        "사진 파일이 없거나 사진 내용을 알 수 없어 고칠 수 없는 것은 지어내지 말고, "
        "무엇이 문제이고 사용자가 무엇을 해 주면 되는지 쉬운 한국어로 알려 주세요."
    )
    print(json.dumps({"decision": "block", "reason": reason}, ensure_ascii=False))
    sys.exit(0)


if __name__ == "__main__":
    main()

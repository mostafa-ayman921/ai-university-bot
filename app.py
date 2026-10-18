import os
import re
import time
from pathlib import Path

import requests
import streamlit as st
from google import genai
from google.genai import types

MODEL = "gemini-2.5-flash"
FILES_DIR = Path("files")
ROOT_FOLDER_ID = "10bpMPWKQ4EJ6UWEBwysqNdTEC6Tsh6B2"  # الفولدر الرئيسي في Drive
DRIVE_API = "https://www.googleapis.com/drive/v3/files"

SYSTEM = """أنت مساعد دراسة لطلاب IT سنة أولى. جاوب من الملفات المرفقة فقط، ولو المعلومة مش موجودة قول كده ومتألفش.

حسب الطلب:
- تلخيص: نقاط مختصرة مرتبة + أهم المصطلحات.
- شرح: ابدأ ببساطة ومثال، وبعدين التفاصيل.
- اسايمنت: وضّح خطوات الحل ثم الإجابة النهائية.
- مراجعة قبل الامتحان: أهم النقاط + الأسئلة المتوقعة + أخطاء شائعة.
- امتحان: اعمل امتحان (MCQ + صح/غلط + مقالي) من المحتوى، والإجابات في آخر الرد. ولو قلت "صححلي" صحح إجاباتي واشرح الغلط.

الرد بالعربي المصري، والمصطلحات التقنية بالإنجليزي."""

st.set_page_config(page_title="مساعد المذاكرة", page_icon="📚")
client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])
DRIVE_KEY = os.environ.get("DRIVE_API_KEY", "")


def list_children(folder_id):
    files, token = [], None
    while True:
        r = requests.get(
            DRIVE_API,
            params={
                "q": f"'{folder_id}' in parents and trashed=false",
                "fields": "nextPageToken, files(id,name,mimeType)",
                "pageSize": 1000,
                "pageToken": token,
                "key": DRIVE_KEY,
                "supportsAllDrives": True,
                "includeItemsFromAllDrives": True,
            },
            timeout=30,
        )
        r.raise_for_status()
        data = r.json()
        files += data.get("files", [])
        token = data.get("nextPageToken")
        if not token:
            return files


def sync_folder(folder_id, dest: Path, errors: list):
    dest.mkdir(parents=True, exist_ok=True)
    try:
        children = list_children(folder_id)
    except Exception as e:
        errors.append(f"{dest}: {str(e)[:150]}")
        return
    for f in children:
        name = re.sub(r'[\\/:*?"<>|]', "_", f["name"]).strip()
        if f["mimeType"] == "application/vnd.google-apps.folder":
            sync_folder(f["id"], dest / name, errors)
        elif f["mimeType"] == "application/pdf":
            path = dest / name
            if path.exists():  # اتحمّل قبل كده
                continue
            try:
                r = requests.get(
                    f"{DRIVE_API}/{f['id']}",
                    params={"alt": "media", "key": DRIVE_KEY, "supportsAllDrives": True},
                    timeout=120,
                )
                r.raise_for_status()
                path.write_bytes(r.content)
            except Exception as e:
                errors.append(f"{name}: {str(e)[:150]}")


@st.cache_data(ttl=3600, show_spinner="بحدّث الملفات من Drive...")
def sync_drive():
    errors = []
    if not DRIVE_KEY:
        return time.time(), ["DRIVE_API_KEY مش موجود في Secrets"]
    sync_folder(ROOT_FOLDER_ID, FILES_DIR, errors)
    return time.time(), errors


if st.sidebar.button("🔄 حدّث من Drive"):
    sync_drive.clear()
synced_at, sync_errors = sync_drive()
for err in sync_errors:
    st.sidebar.warning(err)


@st.cache_resource(show_spinner="بحمّل الملفات...")
def upload_subject(subject: str, synced_at: float):
    pdfs = sorted((FILES_DIR / subject).glob("*.pdf"))
    return [
        client.files.upload(
            file=str(p),
            config=types.UploadFileConfig(display_name=f"doc{i}", mime_type="application/pdf"),
        )
        for i, p in enumerate(pdfs)
    ]


subjects = sorted({str(p.parent.relative_to(FILES_DIR)) for p in FILES_DIR.rglob("*.pdf")})
if not subjects:
    st.error("مفيش PDFs اتحملت. شوف التحذير اللي في الجنب.")
    st.stop()

subject = st.sidebar.selectbox("المادة", subjects)
quick = st.sidebar.radio(
    "طلب سريع",
    ["—", "لخصلي المادة", "مراجعة قبل الامتحان", "اعملي امتحان", "حل الاسايمنت"],
)
if st.sidebar.button("محادثة جديدة"):
    st.session_state.pop("chat", None)
    st.session_state.pop("msgs", None)

if st.session_state.get("subject") != subject:
    st.session_state.subject = subject
    st.session_state.pop("chat", None)
    st.session_state.msgs = []

if "chat" not in st.session_state:
    st.session_state.chat = client.chats.create(
        model=MODEL,
        config=types.GenerateContentConfig(system_instruction=SYSTEM),
    )
    st.session_state.msgs = []
    st.session_state.first = True

st.title(f"📚 {subject.split(os.sep)[-1]}")
for m in st.session_state.msgs:
    st.chat_message(m["role"]).write(m["text"])

prompt = st.chat_input("اسأل أي حاجة...")
if not prompt and quick != "—" and st.sidebar.button("ابعت الطلب السريع"):
    prompt = quick

if prompt:
    st.chat_message("user").write(prompt)
    parts = [prompt]
    if st.session_state.first:  # الملفات بتتبعت مرة واحدة في أول رسالة
        parts = upload_subject(subject, synced_at) + [prompt]
        st.session_state.first = False
    with st.chat_message("assistant"):
        with st.spinner("..."):
            text = st.session_state.chat.send_message(parts).text
        st.write(text)
    st.session_state.msgs += [
        {"role": "user", "text": prompt},
        {"role": "assistant", "text": text},
    ]

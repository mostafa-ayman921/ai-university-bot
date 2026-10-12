import os
import time
from pathlib import Path

import gdown
import streamlit as st
from google import genai
from google.genai import types

MODEL = "gemini-2.5-flash"
FILES_DIR = Path("files")
FOLDER_URL = "https://drive.google.com/drive/folders/10bpMPWKQ4EJ6UWEBwysqNdTEC6Tsh6B2"

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


@st.cache_data(ttl=3600, show_spinner="بحدّث الملفات من Drive...")
def sync_drive():
       gdown.download_folder(url=FOLDER_URL, output=str(FILES_DIR), quiet=True)
    return time.time()


if st.sidebar.button("🔄 حدّث من Drive"):
    sync_drive.clear()
synced_at = sync_drive()


@st.cache_resource(show_spinner="بحمّل الملفات...")
def upload_subject(subject: str, synced_at: float):
    pdfs = sorted((FILES_DIR / subject).glob("*.pdf"))
    return [client.files.upload(file=str(p)) for p in pdfs]


subjects = sorted({str(p.parent.relative_to(FILES_DIR)) for p in FILES_DIR.rglob("*.pdf")})
if not subjects:
    st.error("مفيش PDFs اتحملت. اتأكد إن الفولدر Anyone with the link.")
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

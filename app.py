from flask import Flask, request, jsonify, send_from_directory
from youtube_transcript_api import YouTubeTranscriptApi
from youtube_transcript_api import YouTubeTranscriptApi, FetchedTranscript
import anthropic
import groq
import os
import tempfile
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__)

groq_client = groq.Groq(api_key=os.getenv("GROQ_API_KEY"))
anthropic_client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))

def extract_video_id(url):
    import re
    patterns = [
        r'v=([a-zA-Z0-9_-]{11})',
        r'youtu\.be/([a-zA-Z0-9_-]{11})',
    ]
    for p in patterns:
        m = re.search(p, url)
        if m:
            return m.group(1)
    return None

@app.route('/')
def index():
    return send_from_directory('.', 'index.html')

@app.route('/transcript', methods=['POST'])
def get_transcript():
    url = request.json.get('url')
    video_id = extract_video_id(url)
    if not video_id:
        return jsonify({'error': '无法识别YouTube链接'}), 400
    try:
        ytt_api = YouTubeTranscriptApi()
        fetched = ytt_api.fetch(video_id, languages=['en'])
        transcript = [{'start': s.start, 'duration': s.duration, 'text': s.text} for s in fetched]
        return jsonify({'transcript': transcript, 'video_id': video_id})
    except Exception as e:
        return jsonify({'error': f'无法获取字幕：{str(e)}'}), 400

@app.route('/transcribe', methods=['POST'])
def transcribe_audio():
    if 'audio' not in request.files:
        return jsonify({'error': '没有收到音频'}), 400
    audio_file = request.files['audio']
    with tempfile.NamedTemporaryFile(suffix='.webm', delete=False) as tmp:
        audio_file.save(tmp.name)
        tmp_path = tmp.name
    try:
        with open(tmp_path, 'rb') as f:
            result = groq_client.audio.transcriptions.create(
                model="whisper-large-v3",
                file=("audio.webm", f, "audio/webm"),
            )
        return jsonify({'text': result.text})
    except Exception as e:
        return jsonify({'error': str(e)}), 500
    finally:
        os.unlink(tmp_path)

@app.route('/score', methods=['POST'])
def score():
    data = request.json
    original = data.get('original', '')
    user_text = data.get('user_text', '')
    
    prompt = f"""你是一个英语精听练习的评分助手。

原文：
{original}

学习者复述：
{user_text}

请用JSON格式返回以下内容（只返回JSON，不要其他文字）：
{{
  "score": 0到100的整数,
  "correct": ["说对的关键词或短语列表"],
  "missed": ["漏掉的关键词或短语列表"],
  "wrong": ["说错的地方，格式为'说成了X，应该是Y'"],
  "comment": "一句话点评，鼓励为主，指出最主要的问题"
}}

评分标准：语义等价的表达视为正确（如wanna=want to）。"""

    message = anthropic_client.messages.create(
    model="claude-sonnet-4-6",
    max_tokens=1000,
    system="你只能返回纯JSON，不要任何markdown格式，不要```json标记，直接返回{}开头的JSON。",
    messages=[{"role": "user", "content": prompt}]
)
    
    import json
    try:
        result = json.loads(message.content[0].text)
    except:
        result = {"score": 0, "comment": message.content[0].text, "correct": [], "missed": [], "wrong": []}
    
    return jsonify(result)

@app.route('/summary', methods=['POST'])
def summary():
    data = request.json
    scores = data.get('scores', [])
    all_missed = data.get('all_missed', [])
    
    avg = sum(s['score'] for s in scores) / len(scores) if scores else 0
    
    prompt = f"""你是英语精听练习教练。学习者完成了一段视频的精听练习。

平均得分：{avg:.0f}分
各段得分：{[s['score'] for s in scores]}
高频遗漏词汇：{all_missed[:20]}

请用JSON返回总结报告（只返回JSON）：
{{
  "overall_score": 四舍五入后的整数平均分,
  "grade": "A/B/C/D之一",
  "summary": "2-3句整体评价",
  "weak_spots": ["最需要改进的2-3个方面"],
  "vocabulary": [{{"word": "词", "meaning": "中文意思", "example": "例句"}}],
  "tips": ["1-3条具体可执行的提升建议"]
}}"""

    message = anthropic_client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=1500,
        messages=[{"role": "user", "content": prompt}]
    )
    
    import json
    try:
        result = json.loads(message.content[0].text)
    except:
        result = {"overall_score": avg, "summary": message.content[0].text}
    
    return jsonify(result)

import json as json_module

FAVORITES_FILE = 'favorites.json'

@app.route('/favorites', methods=['GET'])
def get_favorites():
    if not os.path.exists(FAVORITES_FILE):
        return jsonify([])
    with open(FAVORITES_FILE, 'r', encoding='utf-8') as f:
        return jsonify(json_module.load(f))

@app.route('/favorites', methods=['POST'])
def add_favorite():
    data = request.json
    favorites = []
    if os.path.exists(FAVORITES_FILE):
        with open(FAVORITES_FILE, 'r', encoding='utf-8') as f:
            favorites = json_module.load(f)
    # 避免重复
    if not any(fav['url'] == data['url'] for fav in favorites):
        favorites.insert(0, {
            'url': data['url'],
            'title': data.get('title', '未知视频'),
            'date': data.get('date', ''),
            'score': data.get('score', '-')
        })
    with open(FAVORITES_FILE, 'w', encoding='utf-8') as f:
        json_module.dump(favorites, f, ensure_ascii=False, indent=2)
    return jsonify({'ok': True})

if __name__ == '__main__':
    app.run(debug=True, port=5000)
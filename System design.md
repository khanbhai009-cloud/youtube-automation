
# SYSTEM DESIGN — YouTube AI Factory v1.0
### Remotion + 3-Tier Mastermind Architecture | **Updated:** April 2026
## SECTION 1 — SYSTEM KA BIRDS EYE VIEW
```text
┌───────────────────────────────────────────────────────────────────────────────┐
│                      YOUTUBE 3-TIER MASTERMIND PIPELINE                       │
│                                                                               │
│  [CMO 1]                 [CMO 2]                   [CMO 3]                    │
│  The Visionary    →      The Orchestrator    →     The Packager               │
│                                                                               │
│  Channel Data            Script Breakdown          Asset Assembly             │
│  Trend Analysis          Variety Engine (Images)   Remotion TSX Coder         │
│  Groq Script Agent       Voice + Timestamps        Thumbnail & SEO            │
└───────────────────────────────────────────────────────────────────────────────┘

```
**Key Mechanics:**
 * **Pre-Render QC:** Render hone se pehle Collection Box mein Visual Director sab check karta hai.
 * **Skill Injection:** Remotion coder ke paas skill.md hai for pro-level After Effects animations.
 * **Targeted Regeneration:** Sirf wahi asset dubara banega jo fail hua hai, pura loop nahi ghoomega.
## SECTION 2 — COMPLETE VISUAL FLOWCHART (Mermaid.js)
# YOUTUBE AI FACTORY - SYSTEM DESIGN v2.0
### Architecture: 3-Tier Mastermind + Remotion Engine
**Status:** Upgrading from Monolithic Pipeline to Microservices

---

## SECTION 1 — ARCHITECTURE EVOLUTION (Old vs. New)

**Purane System ki Problems (The 6/10 Spaghetti):**
- **Sequential Bottleneck:** Ek scene fail hone par pura pipeline ruk jata tha.
- **FFmpeg Limitations:** Sirf basic filters aur static color grading milti thi.
- **Race Conditions:** Ek hi prompt aane par assets overwrite ho jate the.

**Naya v2.0 System (The 10/10 Mastermind):**
- **Micro-Masterminds:** Ek single loop ki jagah 3 alag `node_cmo` scripts (Visionary, Orchestrator, Packager).
- **Remotion Engine:** FFmpeg ki jagah React (`.tsx`) code use hoga fluid motion graphics, 2.5D parallax aur ease-in/out animations ke liye. FFmpeg ab sirf end me chote scenes ko jodne (stitch) ke kaam aayega.
- **Parallel Processing:** Video rendering, Thumbnail creation, aur SEO ek sath parallel threads me run honge.

---

## SECTION 2 — SYSTEM FLOWCHART (Mermaid.js)
```mermaid
flowchart TD
    A([🕐 Trigger: Scheduled Video Run]) --> B[main.py]

    subgraph CMO_1["🧠 CMO 1: The Visionary (node_cmo_1.py)"]
        direction TB
        B --> C1[Trend Analytics & Channel Research]
        C1 --> SA[Script Agent - Groq]
        SA --> VD1{Pre-QC Threshold > 8/10}
        VD1 -- "Fail" --> SA
        VD1 -- "Pass" --> OUT1[Approved Master Script]
    end

    OUT1 --> CMO_2

    subgraph CMO_2["🎬 CMO 2: The Orchestrator (node_cmo_2.py)"]
        direction TB
        IN2[Scene-by-Scene Breakdown] --> VA[Voice Agent + Whisper TTS]
        IN2 --> IA[Image Agent + Variety Engine]
        
        VA --> CB[(Collection Box)]
        IA --> CB
        
        CB --> VD2{Visual Director\nPre-Render Validation}
        VD2 -- "Bad Image" --> IA
        VD2 -- "Bad Audio" --> VA
        VD2 -- "Approved" --> OUT2[Verified Assets & Timestamps]
    end

    OUT2 --> CMO_3

    subgraph CMO_3["📦 CMO 3: The Packager (node_cmo_3.py)"]
        direction LR
        IN3[Parallel JSON Split] --> SPLIT{Parallel Threading}
        SPLIT -->|Video JSON| V_JSON[Remotion Coder Agent\nReads skill.md for styling]
        SPLIT -->|Thumb JSON| T_JSON[Thumbnail Agent]
        SPLIT -->|SEO JSON| S_JSON[SEO Agent]
    end

    subgraph RENDER["⚙️ THE CLOUD ENGINE (Docker / Hugging Face)"]
        direction TB
        V_JSON --> REM[Remotion Engine\nGenerates UI/Motion via React]
        REM -->|Scene MP4s| FFM[FFmpeg Fast Stitching\n+ BGM/SFX Mixing]
    end

    subgraph UPLOAD["🚀 SCHEDULER & YOUTUBE API"]
        direction TB
        FFM --> UPL[YouTube API Upload]
        T_JSON --> UPL
        S_JSON --> UPL
    end
    
    UPL --> DONE([✅ Video Live on YouTube])
'''
## SECTION 3 — PROJECT FILE STRUCTURE
Jab workspace banaoge, toh folders aur files is structure mein hone chahiye:
```text
youtube-ai-factory/
│
├── main.py                     # Entry point & Scheduler setup
├── config.py                   # API Keys & Environment Variables 
├── skill.md                    # THE SECRET SAUCE: Motion graphics rules for Remotion
├── Dockerfile                  # Hugging Face deployment (Python + Node.js + FFmpeg)
├── package.json                # Remotion dependencies
│
├── data/
│   ├── channel_analytics.json  # Fetched channel data
│   ├── style_tracker.json      # Visual variety rotation tracker
│   └── logs/                   # System execution logs
│
├── mastermind/                 # The 3-Tier Brain
│   ├── graph.py                # LangGraph orchestration (connecting all 3 CMOs)
│   ├── state.py                # TypedDict for agent states
│   ├── node_cmo_1.py           # The Visionary (Scripting)
│   ├── node_cmo_2.py           # The Orchestrator (Scenes & Collection Box)
│   └── node_cmo_3.py           # The Packager (JSON split & Metadata)
│
├── agents/                     # The Workers
│   ├── script_agent.py         # Writes the actual text
│   ├── voice_agent.py          # Whisper TTS + Timestamps
│   ├── image_agent.py          # T2I pipeline with Variety Engine
│   ├── visual_director.py      # CR Agent for Quality Control
│   ├── remotion_coder.py       # LLM that writes .tsx code using skill.md
│   ├── thumbnail_agent.py      # Generates CTR-heavy thumbnails
│   └── seo_agent.py            # Titles, descriptions, and tags
│
├── tools/                      # Execution Scripts & APIs
│   ├── llm.py                  # Groq/Cerebras fallback wrapper
│   ├── remotion_bridge.py      # Python subprocess that runs 'npx remotion render'
│   ├── ffmpeg_stitcher.py      # Stitches 10s scenes into final video
│   ├── youtube_api.py          # Automated upload handling
│   └── imgbb_uploader.py       # Permanent image hosting
│
└── src/                        # Remotion React Workspace (Dynamic)
    ├── index.ts                # Remotion entry point
    └── Video.tsx               # Base layout (Agents overwrite this dynamically)

```
## SECTION 4 — FALLBACK & LOOP MATRIX
| Component | Target/Agent | Fallback Action / Loop Logic |
|---|---|---|
| **CMO 1 Verification** | Script Agent | 8/10 nahi mila toh regenerate. Max 3 loops, then Drop. |
| **Visual Director (CR)** | Image / Voice Agent | Targeted Fix. Sirf kharab asset regenerate hoga. |
| **Remotion Syntax** | Remotion Coder | Code me error aaya toh compiler log wapas LLM ko jayega fix ke liye. |
| **Image Generation** | Cloudflare / FLUX | Fails → Pollinations.ai → Fails → Puter.js |
| **LLM Calls** | Groq (Llama 70B) | Rate Limit/Fail → Cerebras (Llama 70B) |
*YOUTUBE AI FACTORY v1.0 — Architecture designed for Mobile-First Execution & Cloud Rendering*
        'query': query,
        'token': api_key,
        'fields': 'id,name,previews',
        'filter': 'duration:[0.5 TO 5]'
    }
    response = requests.get(url, params=params)
    return response.json()

def download_sfx(sound_id, api_key, output_path):
    url = f"https://freesound.org/apiv2/sounds/{sound_id}/"
    headers = {'Authorization': f'Token {api_key}'}
    response = requests.get(url, headers=headers)
    preview_url = response.json()['previews']['preview-hq-mp3']
    
    sfx_response = requests.get(preview_url)
    with open(output_path, 'wb') as f:
        f.write(sfx_response.content)

# Usage
api_key = os.environ.get('FREESOUND_API_KEY')
results = search_freesound('dramatic sting', api_key)
if results['results']:
    download_sfx(results['results'][0]['id'], api_key, 'sting.mp3')
```

### Advanced Audio Processing Libraries:
```python
import librosa
import soundfile as sf
from pydub import AudioSegment
import numpy as np

def enhance_audio(audio_path):
    # Load audio
    y, sr = librosa.load(audio_path)
    
    # Noise reduction
    y_denoised = librosa.effects.preemphasis(y)
    
    # Dynamic range compression
    y_compressed = librosa.effects.percussive(y_denoised)
    
    # Equalization
    y_eq = librosa.effects.harmonic(y_compressed)
    
    # Normalization
    y_normalized = librosa.util.normalize(y_eq)
    
    # Save enhanced audio
    sf.write('enhanced_audio.wav', y_normalized, sr)
    
    return 'enhanced_audio.wav

def add_atmospheric_sfx(voice_path, sfx_paths, output_path):
    voice = AudioSegment.from_wav(voice_path)
    
    # Mix SFX at different points
    final = voice
    for i, sfx_path in enumerate(sfx_paths):
        sfx = AudioSegment.from_mp3(sfx_path)
        sfx = sfx - 20  # Reduce volume by 20dB
        position = i * 30000  # Every 30 seconds
        final = final.overlay(sfx, position=position)
    
    final.export(output_path, format='wav')
```

## 4. Library Suggestions: Image-to-Video Motion aur Temporal Consistency

**Cloud-Friendly Libraries (No Heavy GPU Usage):**

### 1. RunwayML API (Cloud-based Video Generation)
```python
import requests

def generate_motion_video(image_path, prompt, api_key):
    url = "https://api.runwayml.com/v1/image_to_video"
    headers = {"Authorization": f"Bearer {api_key}"}
    
    with open(image_path, 'rb') as img:
        files = {'image': img}
        data = {
            'model': 'gen-3-alpha-turbo',
            'prompt': prompt,
            'duration': 5,
            'ratio': '16:9'
        }
        response = requests.post(url, files=files, data=data, headers=headers)
    
    return response.json()['video_url']
```

### 2. Pika Labs API (Motion from Static Images)
```python
def create_motion_video(image_url, motion_prompt):
    url = "https://api.pika.art/v1/motion"
    payload = {
        "image_url": image_url,
        "motion_prompt": motion_prompt,
        "duration": 4,
        "aspect_ratio": "16:9"
    }
    response = requests.post(url, json=payload, headers=headers)
    return response.json()
```

### 3. Temporal Consistency with Stable Diffusion (Cloud API)
```python
# Using Replicate or Hugging Face Inference API
import replicate

def enhance_temporal_consistency(image_sequence, prompt):
    model = replicate.models.get("stability-ai/stable-diffusion")
    outputs = []
    
    for img in image_sequence:
        output = model.predict(
            prompt=f"{prompt}, consistent with previous frame",
            image=img,
            guidance_scale=7.5
        )
        outputs.append(output)
    
    return outputs
```

### 4. Deforum (Lightweight Version for Cloud)
```python
# Use deforum through RunPod or Modal for cloud execution
def run_deforum_animation(prompt, keyframes):
    # Deploy to cloud GPU
    # Process animation frames
    # Return video URL
    pass
```

### 5. OpenCV + Optical Flow for Motion Estimation
```python
import cv2
import numpy as np

def estimate_motion(frame1, frame2):
    # Calculate optical flow
    flow = cv2.calcOpticalFlowFarneback(
        cv2.cvtColor(frame1, cv2.COLOR_BGR2GRAY),
        cv2.cvtColor(frame2, cv2.COLOR_BGR2GRAY),
        None, 0.5, 3, 15, 3, 5, 1.2, 0
    )
    
    # Apply motion to stabilize or enhance
    h, w = flow.shape[:2]
    flow_map = np.column_stack((np.repeat(np.arange(w), h),
                               np.tile(np.arange(h), w)))
    flow_map = flow_map.reshape(h, w, 2) + flow
    
    return flow_map

def create_smooth_motion_video(image_paths, output_path):
    frames = [cv2.imread(img) for img in image_paths]
    
    # Apply motion smoothing
    smoothed_frames = []
    for i in range(len(frames)-1):
        motion = estimate_motion(frames[i], frames[i+1])
        # Apply smoothing algorithm
        smoothed = cv2.remap(frames[i+1], motion, None, cv2.INTER_LINEAR)
        smoothed_frames.append(smoothed)
    
    # Write video
    height, width = frames[0].shape[:2]
    video = cv2.VideoWriter(output_path, cv2.VideoWriter_fourcc(*'mp4v'), 30, (width, height))
    for frame in smoothed_frames:
        video.write(frame)
    video.release()
```

## 5. The Logic Architect Reality: Scalability Assessment

**Rating: 6/10 - "Functional but Fragile Spaghetti"**

**What's Good:**
- Modular agent architecture with clear separation of concerns
- Feedback loops (critic, FFmpeg self-healing) ka concept solid hai
- Shared state approach centralized control provide karta hai
- Error handling aur logging decent level pe hai

**Spaghetti Mess Issues:**
- Tight coupling between agents - ek agent ka failure doosre ko break kar deta hai
- Sequential processing bottleneck - parallel execution ka absence scalability ko kill kar raha hai
- State mutations scattered across phases bina proper validation ke
- No microservices architecture - sab kuch ek monolithic loop me
- External API dependencies tightly coupled - no fallback strategies for complete API outages
- No horizontal scaling - single pipeline instance only
- Memory leaks potential: state object continuously grow karta hai with logs aur feedback

**Scalability Problems:**
- Agar 10 videos same time generate karne ho to alag-alag processes spawn karne padenge
- GPU/CPU intensive tasks (FFmpeg rendering) sequential hain
- Database/storage layer nahi hai - sab kuch memory me
- No load balancing ya queue system
- Single point of failure: agar ek agent hang ho jaye to pura pipeline ruk jata hai

**Recommended Architecture Overhaul:**
1. **Microservices Migration:** Har agent ko separate service banao with message queues (RabbitMQ/Redis)
2. **Parallel Processing:** Scene rendering ko concurrent banao using multiprocessing
3. **Database Layer:** Agent state ko persistent storage me move karo
4. **Circuit Breakers:** External API calls ke liye circuit breaker pattern implement karo
5. **Async Processing:** IO-bound tasks (image downloads, API calls) ko async banao
6. **Container Orchestration:** Kubernetes/Docker Compose se scaling enable karo

**Final Verdict:** Current system ek proof-of-concept hai jo basic automation ke liye kaam karta hai, but production-scale YouTube factory banane ke liye complete rearchitecture chahiye.</content>
<parameter name="filePath">/workspaces/youtube-automation/System design.md

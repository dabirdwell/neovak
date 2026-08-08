#!/usr/bin/env python3
"""M0 probe: minimal MiniMax H3 FL2VA text-to-video on the Studio (MPS).
Submits a tiny AV generation, polls to completion, records wall time and
peak ComfyUI RSS, ffprobes the output. Run: nohup python3 m0_probe.py > /tmp/m0_run.log"""
import json, time, subprocess, urllib.request, sys, os

BASE = "http://127.0.0.1:8188"
G = {
 "1": {"class_type":"UNETLoader","inputs":{"unet_name":os.environ.get("M0_UNET","minimax_h3_fl2va_pruned_int8_convrot.safetensors"),"weight_dtype":"default"}},
 "2": {"class_type":"MiniMaxH3SigmaShift","inputs":{"model":["1",0],"shift_video":12.0,"shift_audio":3.0}},
 "3": {"class_type":"CLIPLoader","inputs":{"clip_name":"qwen3vl_32b_minimax_h3_int8_convrot.safetensors","type":"minimax"}},
 "4": {"class_type":"VAELoader","inputs":{"vae_name":"minimax_h3_video_vae_fp16.safetensors"}},
 "5": {"class_type":"VAELoader","inputs":{"vae_name":"minimax_h3_audio_vae_fp32.safetensors"}},
 "6": {"class_type":"MiniMaxH3ImageToVideo","inputs":{"clip":["3",0],"vae":["4",0],
       "prompt":"A tabby cat walks across a sunlit wooden porch, gentle morning light, soft ambient birdsong.",
       "width":512,"height":288,"length":22}},
 "7": {"class_type":"CLIPTextEncode","inputs":{"clip":["3",0],"text":"blurry, distorted, low quality"}},
 "8": {"class_type":"KSampler","inputs":{"model":["2",0],"positive":["6",0],"negative":["7",0],
       "latent_image":["6",1],"seed":424242,"steps":12,"cfg":5.0,
       "sampler_name":"euler","scheduler":"simple","denoise":1.0}},
 "9": {"class_type":"VAEDecode","inputs":{"samples":["8",0],"vae":["4",0]}},
 "10":{"class_type":"VAEDecodeAudio","inputs":{"samples":["8",0],"vae":["5",0]}},
 "11":{"class_type":"CreateVideo","inputs":{"images":["9",0],"fps":24,"audio":["10",0]}},
 "12":{"class_type":"SaveVideo","inputs":{"video":["11",0],"filename_prefix":"M0_h3_probe","format":"auto","codec":"auto"}},
}

def post(path, obj):
    r = urllib.request.Request(BASE+path, data=json.dumps(obj).encode(),
                               headers={"Content-Type":"application/json"})
    return json.load(urllib.request.urlopen(r, timeout=60))

def comfy_rss_gb():
    try:
        out = subprocess.run(["bash","-c",
          "ps axo rss,command | grep 'main.py --listen' | grep -v grep | awk '{print $1}'"],
          capture_output=True, text=True).stdout.strip().splitlines()
        return max((int(x) for x in out), default=0)/1048576
    except Exception:
        return 0.0

t0 = time.time()
print(f"[{time.strftime('%H:%M:%S')}] submitting", flush=True)
try:
    resp = post("/prompt", {"prompt": G, "client_id": "m0probe"})
except urllib.error.HTTPError as e:
    print("SUBMIT REJECTED:", e.read().decode()[:2000]); sys.exit(1)
pid = resp.get("prompt_id")
print(f"[{time.strftime('%H:%M:%S')}] prompt_id={pid} node_errors={resp.get('node_errors')}", flush=True)

peak = 0.0
while True:
    time.sleep(10)
    peak = max(peak, comfy_rss_gb())
    try:
        h = json.load(urllib.request.urlopen(f"{BASE}/history/{pid}", timeout=30))
    except Exception as e:
        print(f"[{time.strftime('%H:%M:%S')}] poll err {e} rss={peak:.1f}G", flush=True); continue
    if pid in h:
        st = h[pid].get("status",{})
        if st.get("completed") or st.get("status_str") in ("success","error"):
            el = time.time()-t0
            print(f"[{time.strftime('%H:%M:%S')}] DONE status={st.get('status_str')} wall={el:.0f}s peak_rss={peak:.1f}G", flush=True)
            if st.get("status_str") == "error":
                for m in st.get("messages",[]):
                    if m[0] == "execution_error":
                        print("ERROR NODE:", m[1].get("node_type"), "|", str(m[1].get("exception_message"))[:800], flush=True)
            outs = h[pid].get("outputs",{})
            for nid,o in outs.items():
                for k in ("images","video","audio","gifs"):
                    for f in o.get(k,[]):
                        fn = f"/Users/david/Documents/AI-Projects/ComfyUI/output/{f.get('subfolder','')}/{f['filename']}".replace('//','/')
                        print("OUTPUT:", fn, flush=True)
                        subprocess.run(["/opt/homebrew/bin/ffprobe","-v","error","-show_entries",
                                        "format=duration,size:stream=codec_type,codec_name,width,height,sample_rate",
                                        "-of","default=noprint_wrappers=1", fn])
            break
    if time.time()-t0 > 3*3600:
        print("TIMEOUT 3h, abandoning", flush=True); break
    if int(time.time()-t0) % 60 < 10:
        print(f"[{time.strftime('%H:%M:%S')}] running... {time.time()-t0:.0f}s rss={peak:.1f}G", flush=True)

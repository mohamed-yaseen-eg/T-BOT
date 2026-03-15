import os
import time
import json
import base64
import random
import threading
import logging
import requests 

from bot_state import WaitState
from bot_state import DefaultVars

wait = WaitState()
default = DefaultVars()

from func import (
    shutdown_pc, shutdown_countdown, abort_shutdown,
    send_message, send_photo, get_comfy_queue_status,
    generate_image_thread, cancel_generation, lora_slot,
    image_upload, send_settings, save_uploaded_files,
    download_civitai
)

# ===================== BOT SYSTEM =====================
BOT_TOKEN = ""
CHAT_ID = ""
COMFY_URL = "http://127.0.0.1:8000"
last_update_id = 0

# ===== GITHUB DB =====
GITHUB_TOKEN = ""
GITHUB_REPO = ""
GITHUB_BRANCH = "main"

# ===== JSON CACHE =====
JSON_CACHE = {}
JSON_SHA = {}

# ===== LOG SYSTEM =====
logging.basicConfig(
    filename="bot.log",
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s"
)

# ===== FOLDERS PATH =====
EMBEDDINGS_FOLDER = os.path.join(os.path.expanduser("~"), "Documents", "ComfyUI", "models", "embeddings")
SD_LORA = os.path.join(os.path.expanduser("~"), "Documents", "ComfyUI", "models", "Loras", "XL")
ZIT_LORA = os.path.join(os.path.expanduser("~"), "Documents", "ComfyUI", "models", "Loras", "ZIT")


# ===== GITHUB =====
def github_get_json(file_name):

    url = f"https://api.github.com/repos/{GITHUB_REPO}/contents/{file_name}"

    headers = {
        "Authorization": f"Bearer {GITHUB_TOKEN}"
    }

    r = requests.get(url, headers=headers, timeout=20)

    data = r.json()
    sha = r.json()["sha"]

    content = base64.b64decode(data["content"]).decode("utf-8")

    json_data = json.loads(content)

    JSON_CACHE[file_name] = json_data
    JSON_SHA[file_name] = sha

    return json_data

#======================
def github_update_json(file_name, data):

    sha = JSON_SHA[file_name]

    url = f"https://api.github.com/repos/{GITHUB_REPO}/contents/{file_name}"

    headers = {
        "Authorization": f"Bearer {GITHUB_TOKEN}"
    }

    content = base64.b64encode(
        json.dumps(data, indent=4, ensure_ascii=False).encode()
    ).decode()

    payload = {
        "message": f"Update {file_name}",
        "content": content,
        "sha": sha,
        "branch": "main"
    }

    r = requests.put(url, headers=headers, json=payload, timeout=20)

    new_sha = r.json()["content"]["sha"]

    JSON_CACHE[file_name] = data
    JSON_SHA[file_name] = new_sha

#======================
def load_cache_json():
    github_get_json("model_defaults.json")
    github_get_json("lora_defaults.json")
    github_get_json("notes.json")

# ===== DB SYSTEM =====
def load_models():
    try:
        with open("models_list.json", "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        print("Models JSON error:", e)
        return {}

def model_db():
    try:
        return JSON_CACHE.get("model_defaults.json", {})
    except Exception as e:
        print("Model DB JSON error:", e)
        return {}

def lora_db():
    try:
        return JSON_CACHE.get("lora_defaults.json", {})
    except Exception as e:
        print("Lora DB JSON error:", e)
        return {}

# ===================== FUNCTIONS =====================

# ===== MODEL SYSTEM =====
def get_model_category(model_path):
    return model_path.split("\\")[0]

#==========================
def setDefaults(model_name):
    data = model_db().get(model_name)

    if not data:
        send_message("Unknown Model")
        return

    default.sampler = data.get("sampler", default.sampler)
    default.scheduler = data.get("scheduler", default.scheduler)
    default.steps = data.get("steps", default.steps)
    default.cfg = data.get("cfg", default.cfg)
    default.width = data.get("width", default.width)
    default.height = data.get("height", default.height)
    default.recommended = data.get("recommended", "N/A")

# ===== LORA SYSTEM =====
def lora_name(lora):
    if not lora:
        return "None"
    return os.path.basename(lora).replace(".safetensors", "")

def setLoraDefaults(lora):
    data = lora_db().get(lora, {})

    if not data:
        send_message(
            f"Lora: {lora}\n"
            "Unknown Lora\n"
            "Set strength value:"
        )
        return ""
    
    prompt = data.get("prompt", "")
    trigger = data.get("triggerWords", "")
    recommended = data.get("recommended", "N/A")
    
    if trigger:
        send_message(f"prompt: {trigger}")
    if recommended != "N/A":
        send_message(f"recommended: {recommended}")
    return prompt

# ===== JSON SYSTEM =====
def lora_json(full_text):
    try:
        data = JSON_CACHE.get("lora_defaults.json", {})

        lora, prompt, triggerWords, recommended = full_text.split("\n")
        data[lora] = {
            "prompt": prompt,
            "triggerWords": triggerWords,
            "recommended": recommended
        }
        send_message(f"{full_text.split(",")[0]} added / updated successfuly ✅")
       
        github_update_json("lora_defaults.json", data)

    except Exception as e:
        print(f"Error message:{e}")
        send_message("Invalid entry ❌")

#==========================
def model_json(full_text):
    try:
        data = JSON_CACHE.get("model_defaults.json", {})

        model, field, value = full_text.split(",")
        if field in data.get(model, {}):
            data[model][field] = value
            send_message(f"{model} updated ✅")
        else:
            send_message("Invalid entry ❌")

        github_update_json("model_defaults.json", data)

    except Exception as e:
        print(f"Error message:{e}")
        send_message("Invalid entry ❌")


#=========================
def notes_json(full_text):
    try:
        data = JSON_CACHE.get("notes.json", {})

        title, long_text = full_text.split("\n")
        data[title] = long_text
        send_message(f"{full_text.split("\n")[0]} added / updated successfuly ✅")

        github_update_json("notes.json", data)

    except Exception as e:
        print(f"Error message:{e}")
        send_message("Invalid entry ❌")

# ===================== BOT ENGINE =====================
def check_messages():
    global last_update_id
    last_prompt = ""

    url = f"https://api.telegram.org/bot{BOT_TOKEN}/getUpdates"
    try:
        r = requests.get(
            url,
            params={"offset": last_update_id + 1},
            timeout=30
        )
        r = r.json()
    except requests.exceptions.RequestException as e:
        print(f"Telegram connection error: {e}")
        time.sleep(3)
        return

    if not r["result"]:
        return

    for result in r["result"]:
        last_update_id = result["update_id"]

        if "message" not in result:
            continue

        message = result["message"].get("text", "").strip()
        command = message.lower()

    # ==================== COMMANDS =====================
        if command.startswith("/") and (wait.embeddings_selection or wait.pre_embeddings_selection):
            wait.embeddings_selection = False
            wait.pre_embeddings_selection = False

        if command.startswith("/"):
            wait.reset_waiting()

        if command == "/start":
            send_message(f"Hello MOHAMED!...\n What do you have in mind?")
            continue
            
        if command == "/end":
            shutdown_pc()
            continue

        if command == "/abort":
            abort_shutdown()
            continue

        if command == "/cancel":
            cancel_generation()
            continue
        
        if command == "/steps":
            wait.steps = True
            send_message("Steps number:")
            continue

        if command == "/cfg":
            wait.cfg = True
            send_message("CFG value:")
            continue

        if command == "/seed":
            wait.seed = True
            send_message("Seed number (0 for random):")
            continue

        if command == "/model":
            wait.model_category = True
            send_message(
                "Select Model Type:\n"
                "1. SDXL\n"
                "2. illustrious\n"
                "3. ZIT"
            )
            continue

        if command == "/lora":
            lora_slot(wait, default, "Lora")  
            continue

        if command == "/lora_char":
            lora_slot(wait, default, "Char_")            
            continue

        if command == "/lora_cloth":
            lora_slot(wait, default, "Cloth_")            
            continue

        if command == "/lora_style":
            lora_slot(wait, default, "Style_")            
            continue
        
        if command == "/clearlora":
            default.selected_loras = [None, None, None, None]
            default.lora_strengths = [0.0, 0.0, 0.0, 0.0]
            default.filtered_loras_prompts = ["","","",""]
            send_message("All LoRA cleared ✅")
            continue

        if command == "/json":
            load_cache_json()
            send_message("Which json you need to update ?\n /json_lora\n /json_model\n /json_notes")
            continue

        if command == "/json_lora":
            wait.json_lora = True
            send_message("Enter Lora name \nprompt \ntriggerWords \nrecommended")
            continue

        if command == "/json_model":
            wait.json_model = True
            send_message("Enter Model name, what to change (e.g. cfg), new value")
            continue

        if command == "/json_notes":
            wait.json_notes = True
            send_message("Enter title \nlong text")
            continue

        if command == "/sampler":
            wait.sampler = True
            send_message(
                "Choose Sampler Type:\n"
                "1. euler\n"
                "2. euler_ancestral\n"
                "3. dpmpp_2m\n"
                "4. dpmpp_sde\n"
                "5. dpmpp_2m_sde\n"
                "6. dpmpp_3m_sde\n"
                "7. res_multistep\n"
                "8. lcm"
            )
            continue

        if command == "/scheduler":
            wait.scheduler = True
            send_message(
                "Choose Scheduler Type:\n"
                "1. simple\n"
                "2. normal\n"
                "3. karras\n"
                "4. ddim_uniform\n"
                "5. sgm_uniform\n"
                "6. linear\n"
                "7. beta\n"
                "8. exponential"
            )
            continue

        if command == "/denoise":
            wait.denoise = True
            send_message("Denoise value:")
            continue

        if command == "/dimensions":
            wait.width = True
            send_message("Set width:")
            continue
        
        if command == "/setimage":
            if default.sd:
                default.image_selection = 2
                default.denoise = 0.8
                send_message("switch to img2img ✅ \nUpload a new image if required")
            else:
                send_message("❌ img2img available only for SD models ❌")
            continue

        if command == "/clearimage":
            default.image_selection = 1
            default.denoise = 1.0
            send_message("switch to txt2img ✅")
            continue

        if command == "/controlnet":
            if default.sd:
                wait.controlnet = True
                send_message(
                    "Choose ControlNet Type:\n"
                    "0. None\n"
                    "1. Canny\n"
                    "2. Depth\n"
                    "3. OpenPose"
                )
            else:
                send_message("❌ controlnet available only for SD models ❌")
            continue
        
        if command == "/queue":
            running, pending = get_comfy_queue_status()
            total = running + pending
            send_message(f"In-progress ( {running} )  -  In-queue ( {pending} )")
            continue

        if command == "/clearqueue":
            requests.post(f"{COMFY_URL}/queue", json={"clear": True}, timeout=10)
            send_message("Queue cleared ✅")
            continue

        if command == "/settings":
            send_settings(default)
            continue

        if command == "/embeddings":

            if default.sd:
                try:
                    if not os.path.exists(EMBEDDINGS_FOLDER):
                        send_message("Embeddings folder not found ❌")
                        continue

                    files = os.listdir(EMBEDDINGS_FOLDER)

                    if not files:
                        send_message("No embeddings found.")
                        continue

                    files = [
                        f for f in files
                        if os.path.isfile(os.path.join(EMBEDDINGS_FOLDER, f))
                    ]

                    files = sorted(files, key=lambda x: x.lower())

                    default.available_embeddings = [
                        f for f in files
                        if f not in default.selected_embeddings
                        and "neg" not in f.lower()
                        and "negative" not in f.lower()
                        and "positive" not in f.lower()
                        and "pos" not in f.lower()
                        and "quality" not in f.lower()
                        and "po_" not in f.lower()
                    ]

                    msg = ""
                    editing = ""
                    adding = ""

                    if default.selected_embeddings:
                        msg += "🔹 Selected:\n"

                        lines = [l for l in default.embeddings.split(", ") if l.strip()]
                        for i, line in enumerate(lines, 1):
                            parts = line.replace("(embedding:", "").replace(")", "")
                            name, weight = parts.split(":")
                            msg += f"   {name} ({float(weight)})\n"

                        editing = "\nUse /clear_embeddings to reset embeddings\nUse /edit_embeddings to change embeddings"
                    else:
                        msg += "🔹 Selected:\n   None\n"

                    msg += "\n"
                    if default.available_embeddings:
                        msg += "🔸 Available:\n"
                        for i, f in enumerate(default.available_embeddings, 1):
                            msg += f"  {i}. {f.replace('.safetensors','')}\n"
                        adding = "\nSelect embedding, strength:"
                    else:
                        msg += "🔸 Available:\n   None\n"

                    msg += "\nsee /more"
                    msg += editing
                    msg += adding
                    
                    send_message(msg)
                    wait.embeddings_selection = True

                except Exception as e:
                    print(f"Embeddings list error: {e}")
                    send_message("Error reading embeddings ❌")
            else:
                send_message("❌ Embeddings available only for SD models ❌")
            continue

        if command == "/more":

            if default.sd:
                try:
                    if not os.path.exists(EMBEDDINGS_FOLDER):
                        send_message("Embeddings folder not found ❌")
                        continue

                    files = os.listdir(EMBEDDINGS_FOLDER)

                    if not files:
                        send_message("No embeddings found.")
                        continue

                    files = [
                        f for f in files
                        if os.path.isfile(os.path.join(EMBEDDINGS_FOLDER, f))
                    ]

                    files = sorted(files, key=lambda x: x.lower())

                    default.available_embeddings = [
                        f for f in files
                        if f not in default.selected_embeddings
                        and "po_" in f.lower()
                    ]

                    msg = ""
                    editing = ""
                    adding = ""

                    if default.selected_embeddings:
                        msg += "🔹 Selected:\n"

                        lines = [l for l in default.embeddings.split(", ") if l.strip()]
                        for i, line in enumerate(lines, 1):
                            parts = line.replace("(embedding:", "").replace(")", "")
                            name, weight = parts.split(":")
                            msg += f"   {name} ({float(weight)})\n"

                        editing = "\nUse /clear_embeddings to reset embeddings\nUse /edit_embeddings to change embeddings"
                    else:
                        msg += "🔹 Selected:\n   None\n"

                    msg += "\n"
                    if default.available_embeddings:
                        msg += "🔸 Available:\n"
                        for i, f in enumerate(default.available_embeddings, 1):
                            msg += f"  {i}. {f.replace('.safetensors','')}\n"
                        adding = "\nSelect embedding, strength:"
                    else:
                        msg += "🔸 Available:\n   None\n"

                    msg += editing
                    msg += adding
                    send_message(msg)
                    wait.embeddings_selection = True

                except Exception as e:
                    print(f"Embeddings list error: {e}")
                    send_message("Error reading embeddings ❌")
            else:
                send_message("❌ Embeddings available only for SD models ❌")
            continue

        if command == "/edit_embeddings":
            lines = [l for l in default.embeddings.split(", ") if l.strip()]
            result = ""
            if len(lines) > 0:
                for i, line in enumerate(lines, 1):
                    parts = line.replace("(embedding:", "").replace(")", "")
                    name, weight = parts.split(":")
                    result += f"{i}. {name} ({float(weight)})\n"
                send_message(f"Select embedding, strength:\n\n{result}")
                wait.embeddings_selection = False
                wait.embeddings_editing = True
            else:
                send_message(f"No embedding selected")
            continue

        if command == "/clear_embeddings":
            default.embeddings = ""
            default.selected_embeddings = []
            send_message("All embeddings cleared ✅")
            wait.embeddings_selection = False
            continue

        if command == "/pre_embedding":

            if default.sd:                
                try:
                    if not os.path.exists(EMBEDDINGS_FOLDER):
                        send_message("Embeddings folder not found ❌")
                        continue

                    files = os.listdir(EMBEDDINGS_FOLDER)

                    if not files:
                        send_message("No embeddings found.")
                        continue

                    files = [
                        f for f in files
                        if os.path.isfile(os.path.join(EMBEDDINGS_FOLDER, f))
                    ]

                    files = sorted(files, key=lambda x: x.lower())

                    default.available_positive_embeddings = [
                        f for f in files
                        if f not in default.selected_positive_embeddings
                        and (
                            "pos" in f.lower()
                            or "positive" in f.lower()
                            or "quality" in f.lower() 
                        )
                        and "neg" not in f.lower()
                        and "negative" not in f.lower()
                    ]
                    default.available_negative_embeddings = [
                        f for f in files
                        if f not in default.selected_negative_embeddings
                        and (
                            "neg" in f.lower()
                            or "negative" in f.lower()
                        )
                    ]
                    msg = ""
                    is_editing = 0
                    editing = ""
                    is_adding = 0
                    adding = ""

                    if default.selected_positive_embeddings:
                        msg += "🔹 Positive Selected:\n"
                        
                        lines = [l for l in default.positive_embeddings.split(", ") if l.strip()]
                        for i, line in enumerate(lines, 1):
                            parts = line.replace("(embedding:", "").replace(")", "")
                            name, weight = parts.split(":")
                            msg += f"   {name} ({float(weight)})\n"

                        is_editing += 1
                    else:
                        msg += "🔹 Positive Selected:\n   None\n"
                    
                    msg += "\n"

                    if default.selected_negative_embeddings:
                        msg += "🔸 Negative Selected:\n"
                        
                        lines = [l for l in default.negative_embeddings.split(", ") if l.strip()]
                        for i, line in enumerate(lines, 1):
                            parts = line.replace("(embedding:", "").replace(")", "")
                            name, weight = parts.split(":")
                            msg += f"   {name} ({float(weight)})\n"
                            
                        is_editing += 1
                    else:
                        msg += "🔸 Negative Selected:\n   None\n"

                    msg += "\n"

                    if default.available_positive_embeddings:
                        msg += "🔹 Positive Available:\n"
                        for i, f in enumerate(default.available_positive_embeddings, 1):
                            msg += f"  {i}. {f.replace('.safetensors','')}\n"
                        is_adding += 1
                    else:
                        msg += "🔹 Positive Available:\n   None\n"

                    msg += "\n"
                    
                    if default.available_negative_embeddings:
                        msg += "🔸 Negative Available:\n"
                        for i, f in enumerate(default.available_negative_embeddings, 1):
                            msg += f"  {i+len(default.available_positive_embeddings)}. {f.replace('.safetensors','')}\n"
                        is_adding += 1
                    else:
                        msg += "🔸 Negative Available:\n   None\n"

                    if is_editing > 0:
                        editing = "\nUse /clear_pre_embeddings to reset embeddings\nUse /edit_pre_embeddings to change embeddings"

                    if is_adding > 0:
                        adding = "\nSelect embedding, strength:"

                    msg += editing
                    msg += adding
                    send_message(msg)
                    wait.pre_embeddings_selection = True

                except Exception as e:
                    print(f"Embeddings list error: {e}")
                    send_message("Error reading embeddings ❌")
            else:
                send_message("❌ Embeddings available only for SD models ❌")
            continue

        if command == "/edit_pre_embeddings":
            result = ""
            index = 0
            total = 0
            if default.positive_embeddings.strip():
                result += "🔹 Positive Available:\n"
                lines = [l for l in default.positive_embeddings.split(", ") if l.strip()]
                total += len(lines)
                send_message(default.positive_embeddings)
                for i, line in enumerate(lines, 1):
                    parts = line.replace("(embedding:", "").replace(")", "")
                    name, weight = parts.split(":")
                    result += f"{i}. {name} ({float(weight)})\n"
                    index += 1
                result += "\n"
            if default.negative_embeddings.strip():
                result += "🔸 Negative Available:\n"
                lines = [l for l in default.negative_embeddings.split(", ") if l.strip()]
                total += len(lines)
                for i, line in enumerate(lines, 1):
                    parts = line.replace("(embedding:", "").replace(")", "")
                    name, weight = parts.split(":")
                    result += f"{i + index}. {name} ({float(weight)})\n"
            if total > 0:
                send_message(f"Select embedding, strength:\n\n{result}")
            else:
                send_message(f"No embedding selected")
            wait.pre_embeddings_selection = False
            wait.pre_embeddings_editing = True
            continue

        if command == "/clear_pre_embeddings":
            default.positive_embeddings = ""
            default.negative_embeddings = ""
            default.selected_positive_embeddings = []
            default.selected_negative_embeddings = []
            send_message("All pre-embeddings cleared ✅")
            wait.pre_embeddings_selection = False
            continue
        
        if command == "/detailer" and default.sd:
            default.Adetailer = True
            threading.Thread(
                target=generate_image_thread,
                args=(default, last_prompt),
                daemon=True
            ).start()
            continue

        if "civitai.com" in command:
            default.url = "https://civitai.com/api/download/models/" + command.lower().split("modelversionid=")[1].split("&")[0]
            send_message("Send type, subfolder, name\ne.g. model (or lora), illustrious (or ill), Anime 4.0")
            wait.download = True
            continue

        if command.startswith("/"):
            send_message("Unknown command")
            continue

    # ==================== WAIT STATES =====================

        # ==== STEPS ====
        if wait.steps:
            try:
                if message.isdigit():
                    value = int(message)
                    if 1 <= value <= 50:
                        default.steps = int(message)
                        send_message(f"Steps updated to {default.steps} ✅")
                        wait.steps = False
                    else:
                        send_message("❌ Steps must be between 1 and 50")
                        send_message("Please try again")
                else:
                    send_message("Invalid Entry ❌ Please try again")
            except Exception as e:
                print(f"Error message:{e}")
                send_message("Invalid Entry ❌ Please try again")
            continue

        # ==== CFG ====
        if wait.cfg:
            try:
                value = float(message)
                if 1.0 <= value <= 30.0:
                    default.cfg = value
                    send_message(f"CFG updated to {default.cfg} ✅")
                    wait.cfg = False
                else:
                    send_message("❌ CFG must be between 1 and 30\n Please try again")
            except Exception as e:
                print(f"Error message:{e}")
                send_message("Invalid Entry ❌ Please try again")
            continue

        # ==== SEED ====
        if wait.seed:
            try:
                if message.isdigit():
                    if int(message)==0:
                        default.seed_mode = "random"
                        send_message("Seed RANDOM ✅")
                    else:
                        default.seed = int(message)
                        default.seed_mode = "fixed"
                        send_message(f"Seed fixed at {default.seed} ✅")
                    wait.seed = False
                else:
                    send_message("Invalid Entry ❌ Please try again")
            except Exception as e:
                print(f"Error message:{e}")
                send_message("Invalid Entry ❌ Please try again")
            continue

        # ==== MODEL CATEGORY ====
        if wait.model_category:
            category_map = {
                "1": "SDXL",
                "2": "illustrious",
                "3": "ZIT"
            }

            try:
                if message in category_map:
                    selected_category = category_map[message]

                    default.available_filtered_models = load_models().get(selected_category, [])

                    if not default.available_filtered_models:
                        send_message("No models found ❌")
                        wait.model_category = False
                        continue

                    msg = f"Select {selected_category} Model:\n"
                    for i, model in enumerate(default.available_filtered_models, start=1):
                        clean_name = os.path.basename(model).replace(".safetensors", "")
                        msg += f"{i}. {clean_name}\n"
                    
                    send_message(msg)
                    wait.model = True
                    wait.model_category = False
                else:
                    send_message("Invalid choice ❌ Please try again")
            except Exception as e:
                print(f"Error message:{e}")
                send_message("Invalid choice ❌ Please try again")
            continue

        # ==== MODEL ====
        if wait.model:
            model_name = os.path.basename(default.model).replace(".safetensors", "")
            try:
                print(message)
                if ",del" in message:
                    if default.sd:
                        Current_folder = os.path.join(os.path.expanduser("~"), "Documents", "ComfyUI", "models", "checkpoints")
                    elif default.zit:
                        Current_folder = os.path.join(os.path.expanduser("~"), "Documents", "ComfyUI", "models", "unet")
                    else:
                        Current_folder = ""
                    index = int(message.split(",")[0]) - 1
                    if 0 <= index < len(default.available_filtered_models):
                        if default.model == default.available_filtered_models[index]:
                            send_message("Invalid choice ❌ can't delet working model")
                        else:
                            path = os.path.join(Current_folder, default.available_filtered_models[index])
                            if os.path.isfile(path):
                                data = load_models()
                                data[get_model_category(default.model)] = [
                                    m for m in data[get_model_category(default.model)]
                                    if default.available_filtered_models[index] not in m
                                ]
                                with open("models_list.json", "w", encoding="utf-8") as f:
                                    json.dump(data, f, indent=4)
                                os.remove(path)
                                send_message(f"Model {default.available_filtered_models[index]} removed ✅")
                    else:
                        send_message("Invalid choice ❌")
                    wait.model = False
                    continue

                if message.isdigit():
                    index = int(message) - 1
                    if 0 <= index < len(default.available_filtered_models):                                
                        new_model = default.available_filtered_models[index]
                        new_category = get_model_category(new_model)
                        old_category = get_model_category(default.model)

                        default.model = new_model
                        default.sd = get_model_category(default.model) in ["SDXL", "illustrious"] 
                        default.zit = get_model_category(default.model) == "ZIT"

                        if new_category != old_category:
                            default.selected_loras = [None, None, None, None]
                            default.lora_strengths = [0.0, 0.0, 0.0, 0.0]
                            default.filtered_loras_prompts = ["","","",""]

                        model_name = os.path.basename(default.model).replace(".safetensors", "")
                        setDefaults(model_name)
                        send_message(f"Model set to {model_name} ✅\nRecommended: {default.recommended}")
                    else:
                        send_message(f"Invalid choice ❌\n Current model: {model_name}")                    
                else:
                    send_message(f"Invalid Entry ❌\n Current model: {model_name}")
            except Exception as e:
                print(f"Error message:{e}")
                send_message(f"Invalid Entry ❌\n Current model: {model_name}")

            wait.model = False
            continue

        # ==== LORA FLOW ====
        if wait.lora_slot:
            try:
                if "," in message:
                    index = int(message.split(",")[0]) - 1
                    weight = float(message.split(",")[1])
                    default.lora_strengths[index] = weight
                    wait.lora_slot = False
                    send_message(f"Lora updated to {weight}✅")
                    continue
                elif message in ["1", "2", "3", "4"]:
                    default.current_lora_slot = int(message) - 1
                    
                    msg = "0. None\n"
                    
                    if default.sd:
                        LORA_FOLDER = SD_LORA
                    elif default.zit:
                        LORA_FOLDER = ZIT_LORA
                    else:
                        LORA_FOLDER = os.path.join(os.path.expanduser("~"), "Documents", "ComfyUI", "models", "Loras")
                    
                    if not os.path.exists(LORA_FOLDER):
                        send_message("Lora folder not found ❌")
                        continue

                    files = os.listdir(LORA_FOLDER)

                    if not files:
                        send_message("No Lora found.")
                        continue

                    files = [
                        f for f in files
                        if os.path.isfile(os.path.join(LORA_FOLDER, f))
                    ]

                    files = sorted(files, key=lambda x: x.lower())

                    if default.lora_type != "Lora":
                        default.available_filtered_loras = [
                            f for f in files
                            if default.lora_type in f
                        ]
                    else:
                        default.available_filtered_loras = [
                            f for f in files
                            if "Char_" not in f
                            and "Style_" not in f
                            and "Cloth_" not in f
                        ]

                    if default.available_filtered_loras:
                        for i, f in enumerate(default.available_filtered_loras, 1):
                            msg += f"{i}. {f.replace('.safetensors','').replace('Char_','')}\n"
        
                    send_message(msg)
                    wait.lora_choice = True
                    wait.lora_slot = False
                else:
                    send_message("Choose 1, 2, 3 or 4 ❌\n Please try again")
            except Exception as e:
                print(f"Error message:{e}")
                send_message("Choose 1, 2, 3 or 4 ❌\n Please try again")
            continue

        if wait.lora_choice:
            try:
                if message == "0":
                    default.selected_loras[default.current_lora_slot] = None
                    default.lora_strengths[default.current_lora_slot] = 0.0
                    default.filtered_loras_prompts[default.current_lora_slot] = ""
                    send_message("Lora Cleared ✅")
                else:
                    weight = "1"
                    if message.isdigit():
                        index = int(message) - 1
                    elif "," in message:
                        index = int(message.split(",")[0]) - 1
                        weight = message.split(",")[1]
                    else:
                        send_message(f"Invalid Entry ❌\n Current lora: {lora_name(default.selected_loras[default.current_lora_slot])} ({default.lora_strengths[default.current_lora_slot]})")
                        wait.lora_choice = False
                        continue

                    if default.sd:
                        LORA_FOLDER = "XL\\"
                        Current_folder = SD_LORA
                    elif default.zit:
                        LORA_FOLDER = "ZIT\\"
                        Current_folder = ZIT_LORA
                    else:
                        LORA_FOLDER = ""
                        Current_folder = ""
                
                    if 0 <= index < len(default.available_filtered_loras):
                        if weight.lower() == "del":
                            path = os.path.join(Current_folder, default.available_filtered_loras[index])
                            if os.path.isfile(path):
                                os.remove(path)
                                if default.available_filtered_loras[index] in default.selected_loras:
                                    x = default.selected_loras.index(default.available_filtered_loras[index])
                                    default.selected_loras[x] = None
                                    default.lora_strengths[x] = 0.0
                                    default.filtered_loras_prompts[x] = ""
                                send_message(f"{default.available_filtered_loras[index].replace('.safetensors','')} deleted ✅")
                        else: 
                            default.selected_loras[default.current_lora_slot] = LORA_FOLDER + default.available_filtered_loras[index]
                            lora_prompt = setLoraDefaults(default.available_filtered_loras[index].replace('.safetensors',''))
                            default.filtered_loras_prompts[default.current_lora_slot] = lora_prompt
                            if -2.0 <= float(weight) <= 7.0:
                                default.lora_strengths[default.current_lora_slot] = float(weight)
                                send_message(f"Lora updated {os.path.basename(default.selected_loras[default.current_lora_slot]).replace('.safetensors','')} ({default.lora_strengths[default.current_lora_slot]}) ✅")
                            else:
                                send_message(f"❌ Strength must be between -2 and +7\n Current lora: {lora_name(default.selected_loras[default.current_lora_slot])} ({default.lora_strengths[default.current_lora_slot]})")
                    else:
                        send_message(f"Invalid choice ❌\n Current lora: {lora_name(default.selected_loras[default.current_lora_slot])} ({default.lora_strengths[default.current_lora_slot]})")
            except Exception as e:
                print(f"Error message:{e}")
                send_message(f"Invalid Entry ❌\n Current lora: {lora_name(default.selected_loras[default.current_lora_slot])} ({default.lora_strengths[default.current_lora_slot]})")
            wait.lora_choice = False
            continue

        # ==== SAMPLER ====
        if wait.sampler:
            samplers = ["euler", "euler_ancestral", "dpmpp_2m", "dpmpp_sde", "dpmpp_2m_sde", "dpmpp_3m_sde", "res_multistep", "lcm"]
            try:
                if message.isdigit():
                    index = int(message) - 1
                    if 0 <= index < len(samplers):
                        default.sampler = samplers[index]
                        send_message(f"Sampler set to {default.sampler} ✅")
                        wait.sampler = False
                    else:
                        send_message("Invalid choice ❌ Please try again")
                else:
                    send_message("Invalid Entry ❌ Please try again")
            except Exception as e:
                print(f"Error message:{e}")
                send_message("Invalid Entry ❌ Please try again")
            continue

        # ==== SCHEDULER ====
        if wait.scheduler:
            schedulers = ["simple", "normal", "karras", "ddim_uniform", "sgm_uniform", "linear_quadratic", "beta", "exponential"]
            try:
                if message.isdigit():
                    index = int(message) - 1
                    if 0 <= index < len(schedulers):
                        default.scheduler = schedulers[index]
                        send_message(f"Scheduler set to {default.scheduler} ✅")
                        wait.scheduler = False
                    else:
                        send_message(f"Invalid choice ❌ Please try again")
                else:
                    send_message("Invalid Entry ❌ Please try again")
            except Exception as e:
                print(f"Error message:{e}")
                send_message("Invalid Entry ❌ Please try again")
            continue
        
        # ==== DENOISE ====
        if wait.denoise:
            try:
                value = float(message)
                if 0.0 <= value <= 1.0:
                    default.denoise = value
                    send_message(f"denoise updated to {default.denoise} ✅")
                    wait.denoise = False
                else:
                    send_message("denoise must be between 0.0 and 1.0 ❌\n Please try again")
            except Exception as e:
                print(f"Error message:{e}")
                send_message("Invalid Entry ❌ Please try again")
            continue

        # ==== Dimensions ====
        if wait.width:
            x, y = 0, 0
            try:
                if message.isdigit():
                    x = int(message)
                else:
                    x = int(message.split(",")[0])
                    y = int(message.split(",")[1])

                if 100 <= x <= 2048 and 100 <= y <= 2048:
                    default.width = x
                    default.height = y
                    send_message(f"Width set to {default.width}, height set to {default.height} ✅")
                    wait.width = False
                elif 100 <= x <= 2048:
                    default.width = x
                    send_message(f"Width set to {default.width} ✅")
                    wait.width = False
                    send_message("Set height:")
                    wait.height = True
                else:
                    send_message("❌ value must be between 100 and 2048")
                    send_message("Please try again")
                
            except Exception as e:
                print(f"Error message:{e}")
                send_message("Invalid Entry ❌ Please try again")
            continue

        if wait.height:
            try:
                if message.isdigit():
                    value = int(message)
                    if 100 <= value <= 2048:
                        default.height = int(message)
                        send_message(f"Height set to {default.height} ✅")
                        wait.height = False
                    else:
                        send_message("❌ Height must be between 100 and 2048")
                        send_message("Please try again")
                else:
                    send_message("Invalid Entry ❌ Please try again")
            except Exception as e:
                print(f"Error message:{e}")
                send_message("Invalid Entry ❌ Please try again")
            continue

        # ==== EMBEDDINGS
        if wait.embeddings_selection:
            try:
                weight = "1"
                if message.isdigit():
                    index = int(message) - 1
                else:
                    index = int(message.split(",")[0]) - 1
                    weight = message.split(",")[1]

                if 0 <= index < len(default.available_embeddings):

                    if weight.lower() == "del":
                        path = os.path.join(EMBEDDINGS_FOLDER, default.available_embeddings[index])
                        if os.path.isfile(path):
                            os.remove(path)
                            send_message(f"{default.available_embeddings[index].replace('.safetensors','')} deleted ✅")
                    else:
                        value = float(weight)
                        default.selected_embeddings.append(default.available_embeddings[index])
                        default.embeddings += f"(embedding:{default.available_embeddings[index].replace('.safetensors','')}:{value}), "
                        send_message(f"{default.available_embeddings[index].replace('.safetensors','')} added ✅")
                else:
                    send_message("Invalid Number ❌")
            except Exception as e:
                print(f"Error message:{e}")
                send_message("Invalid Entry ❌ Exit embeddings selection")
                wait.embeddings_selection = False
            continue

        if wait.embeddings_editing:
            try:
                lines = [l for l in default.embeddings.split(", ") if l.strip()]
                num = int(message.split(",")[0]) - 1
                weight = message.split(",")[1]
                
                if 0 <= num < len(lines):
                    
                    parts = lines[num].replace("(embedding:", "").replace("), ", "")
                    name = parts.split(":")[0]

                    if weight.lower() == "x":
                        lines.pop(num)
                        default.selected_embeddings.remove(f"{name}.safetensors")
                        send_message(f"{name} removed ❌ Exit editing mode")
                        wait.embeddings_editing = False
                    else:
                        lines[num] = f"(embedding:{name}:{weight})"
                        send_message(f"{name} ({weight}) updated ✅")
                    default.embeddings =", ".join(lines) +(", " if len(lines)>0 else "" )
                else:
                    send_message("Invalid Entry ❌ Exit editing mode")
            except Exception as e:
                print(f"Error message:{e}")
                send_message("Invalid Entry ❌ Exit editing mode")
                wait.embeddings_editing = False
            continue

        if wait.pre_embeddings_selection:
            weight = 1.0
            try:
                if message.isdigit():
                    index = int(message) - 1
                else:
                    index = int(message.split(",")[0]) - 1
                    weight = message.split(",")[1]

                if 0 <= index < len(default.available_positive_embeddings):
                    default.selected_positive_embeddings.append(default.available_positive_embeddings[index])
                    default.positive_embeddings += f"(embedding:{default.available_positive_embeddings[index].replace('.safetensors','')}:{weight}), "
                    send_message(f"{default.available_positive_embeddings[index].replace('.safetensors','')} added ✅")
                elif len(default.available_positive_embeddings) <= index < len(default.available_positive_embeddings) + len(default.available_negative_embeddings):
                    index -= len(default.available_positive_embeddings)
                    default.selected_negative_embeddings.append(default.available_negative_embeddings[index])
                    default.negative_embeddings += f"(embedding:{default.available_negative_embeddings[index].replace('.safetensors','')}:{weight}), "
                    send_message(f"{default.available_negative_embeddings[index].replace('.safetensors','')} added ✅")
                else:
                    send_message("Invalid Number ❌")
            except Exception as e:
                print(f"Error message:{e}")
                send_message("Invalid Entry ❌ Exit embeddings selection")
                wait.pre_embeddings_selection = False
            continue

        if wait.pre_embeddings_editing:
            try:
                num = int(message.split(",")[0]) - 1
                weight = message.split(",")[1]
                positive_lines = [l for l in default.positive_embeddings.split(", ") if l.strip()]
                negative_lines = [l for l in default.negative_embeddings.split(", ") if l.strip()]

                if 0 <= num < len(positive_lines):
                    if weight.lower() == "x":
                        parts = positive_lines[num].replace("(embedding:", "").replace("), ", "")
                        name = parts.split(":")[0]
                        positive_lines.pop(num)
                        default.selected_positive_embeddings.remove(f"{name}.safetensors")
                        send_message(f"{name} removed ❌ Exit editing mode")
                        wait.pre_embeddings_editing = False                       
                    else:
                        parts = positive_lines[num].replace("(embedding:", "").replace("), ", "")
                        name = parts.split(":")[0]
                        positive_lines[num] = f"(embedding:{name}:{weight})"
                        send_message(f"{name} ({weight}) updated ✅")
                    default.positive_embeddings =", ".join(positive_lines) + ", "
                elif len(positive_lines) <= num < len(positive_lines) + len(negative_lines):
                    num -= len(positive_lines)
                    if weight.lower() == "x":
                        parts = negative_lines[num].replace("(embedding:", "").replace("),", "")
                        name = parts.split(":")[0]
                        negative_lines.pop(num)
                        default.selected_negative_embeddings.remove(f"{name}.safetensors")
                        send_message(f"{name} removed ❌ Exit editing mode")
                        wait.pre_embeddings_editing = False                        
                    else:
                        parts = negative_lines[num].replace("(embedding:", "").replace("),", "")
                        name = parts.split(":")[0]
                        negative_lines[num] = f"(embedding:{name}:{weight})"
                        send_message(f"{name} ({weight}) updated ✅")
                    default.negative_embeddings =", ".join(negative_lines) + ", "
                else:
                    send_message("Invalid Entry ❌ Exit editing mode")
            except Exception as e:
                print(f"Error message:{e}")
                send_message("Invalid Entry ❌ Exit editing mode")
                wait.pre_embeddings_editing = False
            continue

        # ==== CONTROLNET FLOW ====
        if wait.controlnet:
            AVAILABLE_PROCESSORS = [
                "CannyEdgePreprocessor",
                "DepthAnythingV2Preprocessor",
                "OpenposePreprocessor"
            ]
            try:
                if message == "0":
                    default.controlnet_mode = "NA"
                    send_message("ControlNet Disabled ✅")
                    wait.controlnet = False
                elif message.isdigit():
                    index = int(message) - 1
                    if 0 <= index < len(AVAILABLE_PROCESSORS):
                        default.controlnet_mode = AVAILABLE_PROCESSORS[index]
                        send_message(f"Processor set to {default.controlnet_mode} ✅")
                        wait.controlnet = False
                        send_message("Upload new image? yes / no")
                        wait.controlnet_image_confirm = True
            except Exception as e:
                print(f"Error message:{e}")
                send_message("Invalid Entry ❌ Please try again")
            continue
            
        if wait.controlnet_image_confirm:
            if command in ["yes", "y"]:
                send_message("Send ControlNet image:")
                wait.controlnet_image_confirm = False
                wait.controlnet_image = True
            elif command in ["no", "n"]:
                send_message("Keeping current image ✅")
                wait.controlnet_image_confirm = False
                wait.controlnet_strength = True
                send_message("Set Controlnet Strength:")
            else:
                send_message("Invalid Entry ❌ Please try again")
            continue

        if wait.controlnet_strength:
            try:
                value = float(message)
                if 0.0 <= value <= 1.0:
                    default.strength = value
                    send_message(f"Strength updated to {default.strength} ✅")
                    wait.controlnet_strength = False
                    send_message("Use img2img mode? yes / no:")
                    wait.img2img = True
                else:
                    send_message("Strength must be between 0.0 and 1.0 ❌\n Please try again")
            except Exception as e:
                print(f"Error message:{e}")
                send_message("Invalid Entry ❌ Please try again")
            continue

        if wait.img2img:
            if command in ["yes", "y"]:
                default.image_selection = 2
                default.denoise = 0.8
                wait.img2img = False
                send_message("switch to img2img ✅")
            elif command in ["no", "n"]:
                default.image_selection = 1
                default.denoise = 1.0
                wait.img2img = False
            else:
                send_message("Invalid Entry ❌ Please try again")
            continue

        #===== Image UPLOAD ====
        if "photo" in result["message"]:
            file_id = result["message"]["photo"][-1]["file_id"]
            image_upload(file_id)
            if wait.controlnet_image:
                wait.controlnet_image = False
                wait.controlnet_strength = True
            continue

        # ==== File Upload ====
        if "document" in result["message"]:
            
            with default.upload_lock:
                if default.uploading:
                    send_message("Upload in progress ⏳ Please wait")
                    continue

            file_id = result["message"]["document"]["file_id"]
            file_name = result["message"]["document"]["file_name"]

            try:
                file_info = requests.get(
                    f"https://api.telegram.org/bot{BOT_TOKEN}/getFile",
                    params={"file_id": file_id},
                    timeout=120
                ).json()

                if not file_info.get("ok"):
                    print("Telegram API error:", file_info)
                    send_message("Telegram file fetch failed ❌")
                    return

                file_path = file_info["result"]["file_path"]
                file_url = f"https://api.telegram.org/file/bot{BOT_TOKEN}/{file_path}"

                response = requests.get(file_url, stream=True, timeout=120)

                temp_path = os.path.join(
                    os.path.expanduser("~"),
                    "Documents",
                    "ComfyUI",
                    "temp_upload",
                    file_name
                )

                with open(temp_path, "wb") as f:
                    for chunk in response.iter_content(8192):
                        if chunk:
                            f.write(chunk)

                with default.upload_lock:
                    default.upload_queue.append({
                        "name": file_name,
                        "temp_path": temp_path
                    })

                send_message(f"Queued: {file_name}")

                # ask type only once
                if not wait.files:
                    send_message(
                        "Select file Type:\n"
                        "1. Embedding\n"
                        "2. XL lora\n"
                        "3. ZIT lora"
                    )
                    wait.files = True

            except Exception as e:
                send_message("Uploading failed ❌")
                print(f"Upload failed: {e}")
            continue

        if wait.files:
            category_map = {
                "1": EMBEDDINGS_FOLDER,
                "2": SD_LORA,
                "3": ZIT_LORA
            }

            try:
                if message in category_map:

                    save_folder = category_map[message]

                    with default.upload_lock:
                        if default.uploading:
                            send_message("Upload already running ⚠️")
                            continue

                    count = len(default.upload_queue)

                    threading.Thread(
                        target=save_uploaded_files,
                        args=(default, save_folder),
                        daemon=True
                    ).start()

                    send_message(f"Uploading {count} files...")

                    wait.files = False

                else:
                    send_message("Invalid choice ❌ Please try again")

            except Exception as e:
                send_message("Upload failed ❌")
                print(f"Upload failed: {e}")
                default.upload_queue.clear()
                wait.files = False
            continue

        # ==== File DOWWNLOAD ====
        if wait.download:
            try:
                model = False
                file_type, folder_name, file_name = [i.strip() for i in message.split(",")]
                if file_type.lower() == "model":
                    model = True
                    folder = "unet" if folder_name.lower() == "zit" else "checkpoints"
                    subfolder = "illustrious" if folder_name.lower().startswith("ill") else folder_name.upper()
                else:
                    folder = "loras"
                    subfolder = "ZIT" if folder_name.lower() == "zit" else "XL"

                save_file = os.path.join(
                    os.path.expanduser("~"),
                    "Documents",
                    "ComfyUI",
                    "models",
                    folder,
                    subfolder,
                    file_name + ".safetensors"
                )

                with default.download_lock:
                    default.download_queue.append(default.url)

                send_message("Queued for download ⏳")

                threading.Thread(
                    target=download_civitai,
                    args=(default, save_file, model, subfolder, file_name),
                    daemon=True
                ).start()

            except Exception as e:
                send_message("Download failed ❌")
                print(f"Download failed: {e}")
                wait.download = False
            continue

        # ========== JSON ==========
        if wait.json_lora:
            lora_json(message)
            wait.json_lora = False
            continue

        if wait.json_model:
            model_json(message)
            wait.json_model = False
            continue

        if wait.json_notes:
            notes_json(message)
            wait.json_notes = False
            continue


        # ========== GENERATE ==========
        if not message:
            continue

        letter_count = sum(1 for c in message if c.isalpha())
        if letter_count < 3:
            send_message("Prompt too short .. Cancelled ❌")
            continue

        if default.seed_mode == "random":
            default.seed = random.randint(1, 999999999999999)

        send_settings(default)

        if "@" in message:
            try:
                parts = message.split("@")
                result = parts[0]
                data = JSON_CACHE.get("notes.json", {})
                for part in parts[1:]:
                    key = ""
                    for c in part:
                        if c.isalpha():
                            key += c
                        else:
                            break

                    if key in data:
                        result += data[key] + part[len(key):]
                    else:
                        result += "@" + part

                message = result
            except Exception as e:
                print(f"@ failed: {e}")
            
        last_prompt = message
        default.last_seed = default.seed

        threading.Thread(
            target=generate_image_thread,
            args=(default, message),
            daemon=True
        ).start()


if __name__ == "__main__":
    load_cache_json()
    print("Bot started...")
    while True:
        check_messages()
        time.sleep(0.5)

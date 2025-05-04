import asyncio
import edge_tts
import gradio as gr
import json
import os
from pathlib import Path
from datetime import datetime
from dotenv import load_dotenv
from playsound import playsound
import threading
import glob

# Load environment variables
load_dotenv()

# Configuration
AUDIO_FOLDER = os.getenv("AUDIO_FOLDER", "audios")
CONFIG_FILE = os.getenv("CONFIG_FILE", "config.json")
Path(AUDIO_FOLDER).mkdir(exist_ok=True)

# Audio format options
AUDIO_FORMATS = ["mp3", "wav", "ogg"]
DEFAULT_FORMAT = "mp3"


def load_config():
    default_config = {
        "favorites": ["es-MX-DaliaNeural", "es-ES-AlvaroNeural"],
        "last_voice": "es-MX-DaliaNeural",
        "audio_format": DEFAULT_FORMAT,
        "last_settings": {
            "speed": 1.0,
            "volume": 1.0,
            "pitch": 0.0,
            "clarity": 0,
            "style": "General",
        },
        "saved_presets": {
            "default": {
                "speed": 1.0,
                "volume": 1.0,
                "pitch": 0.0,
                "clarity": 0,
                "style": "General",
                "voice": "es-MX-DaliaNeural",
                "format": DEFAULT_FORMAT,
            }
        },
    }
    try:
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        # Create default config if not found
        save_config(default_config)
        return default_config


def save_config(config):
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(config, f, indent=2, ensure_ascii=False)


def get_audio_files():
    """Get list of audio files in the audio folder"""
    files = []
    for ext in AUDIO_FORMATS:
        files.extend(glob.glob(f"{AUDIO_FOLDER}/*.{ext}"))

    # Sort by creation time (newest first)
    files.sort(key=os.path.getmtime, reverse=True)

    return files


def get_audio_list_html():
    """Generate HTML for audio list preview"""
    files = get_audio_files()

    if not files:
        return (
            "<div class='text-center p-4 text-gray-500'>No hay audios generados</div>"
        )

    html = "<div class='audio-list' style='max-height: 400px; overflow-y: auto; padding: 10px;'>"

    for i, file_path in enumerate(files[:10]):  # Limit to 10 most recent files
        file_name = os.path.basename(file_path)
        file_date = datetime.fromtimestamp(os.path.getmtime(file_path)).strftime(
            "%d/%m/%Y %H:%M"
        )
        file_size = round(os.path.getsize(file_path) / (1024 * 1024), 2)  # Size in MB

        html += f"""
        <div class='audio-item' style='
            margin-bottom: 12px; 
            padding: 10px; 
            border-radius: 8px; 
            background-color: {"#f0f7ff" if i % 2 == 0 else "#e6f3ff"};
            border: 1px solid #cce0ff;
        '>
            <div style='display: flex; justify-content: space-between; margin-bottom: 6px;'>
                <span style='font-weight: bold;'>{file_name}</span>
                <span style='font-size: 0.8em; color: #666;'>{file_date} ({file_size} MB)</span>
            </div>
            <audio src="file={file_path}" controls style="width: 100%; height: 40px;"></audio>
        </div>
        """

    if len(files) > 10:
        html += f"<div style='text-align: center; padding: 10px; color: #666;'>+ {len(files) - 10} audios más</div>"

    html += "</div>"
    return html


async def get_spanish_voices(gender_filter=None):
    try:
        voices = await edge_tts.list_voices()
        spanish_voices = [v for v in voices if v["Locale"].startswith("es")]

        # Aplicar filtro de género si es necesario
        if gender_filter:
            spanish_voices = [
                v
                for v in spanish_voices
                if v["Gender"].lower() == gender_filter.lower()
            ]

        # Ordenar por país y luego por nombre
        sorted_voices = sorted(
            spanish_voices, key=lambda x: (x["Locale"], x["ShortName"])
        )
        return sorted_voices
    except Exception as e:
        print(f"Error loading voices: {e}")
        return []


def play_audio_file(file_path):
    """Function to play audio file in a separate thread"""
    try:
        if not file_path:
            return "No hay audio para reproducir"

        # Ensure file path is a string
        if isinstance(file_path, dict) and "path" in file_path:
            file_path = file_path["path"]

        if not os.path.exists(file_path):
            return f"Archivo no encontrado: {file_path}"

        threading.Thread(target=playsound, args=(file_path,), daemon=True).start()
        return f"▶️ Reproduciendo: {Path(file_path).name}"
    except Exception as e:
        return f"Error reproduciendo audio: {str(e)}"


async def generar_audio(
    texto, voz, velocidad, intensidad, tono, clarity, estilo, formato
):
    """Function to generate audio from text using edge-tts."""
    try:
        if not texto.strip():
            raise gr.Error("Por favor, ingresa algún texto para el sermón.")

        config = load_config()
        timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
        file_name = f"audio_{timestamp}.{formato}"
        output_file = Path(AUDIO_FOLDER) / file_name

        # Prepare TTS parameters
        communicator = edge_tts.Communicate(
            text=texto,
            voice=voz,
            rate=f"{'+' if velocidad >= 1.0 else ''}{(velocidad - 1.0) * 100:.0f}%",
            volume=f"{'+' if intensidad >= 1.0 else ''}{(intensidad - 1.0) * 100:.0f}%",
        )

        # Actually generate and save the audio file
        await communicator.save(str(output_file))

        # Update configuration
        if voz not in config["favorites"]:
            config["favorites"] = [voz] + config["favorites"][:4]  # Keep only top 5
        config["last_voice"] = voz
        config["audio_format"] = formato
        config["last_settings"] = {
            "speed": float(velocidad),
            "volume": float(intensidad),
            "pitch": float(tono),
            "clarity": clarity,
            "style": estilo,
        }
        save_config(config)

        # Get updated audio list
        audio_list_html = get_audio_list_html()

        # Return values for Gradio components
        return (
            str(output_file),  # Audio component
            gr.update(value=str(output_file)),  # File component
            actualizar_favoritos_html(config),  # Favorites HTML
            actualizar_presets_html(config),  # Presets HTML
            audio_list_html,  # Audio list HTML
            f"✅ Sermón generado: {file_name}",  # Status message
            gr.update(interactive=True),  # Play button
            gr.update(value=str(output_file)),  # Preview audio
        )

    except Exception as e:
        error_msg = f"Error al generar el audio: {str(e)}"
        print(error_msg)
        return (
            None,
            None,
            actualizar_favoritos_html(),
            actualizar_presets_html(),
            get_audio_list_html(),
            error_msg,
            gr.update(interactive=False),
            None,
        )


async def generar_preview(texto, voz, velocidad, intensidad, tono, clarity, estilo):
    """Function to generate a short preview of the audio"""
    try:
        if not texto.strip():
            return None, "Ingresa texto para generar una vista previa"

        # Take only the first few words for the preview
        palabras = texto.split()
        texto_preview = " ".join(palabras[:15]) + "..."

        preview_file = os.path.join(AUDIO_FOLDER, "preview_temp.mp3")

        # Prepare TTS parameters
        communicator = edge_tts.Communicate(
            text=texto_preview,
            voice=voz,
            rate=f"{'+' if velocidad >= 1.0 else ''}{(velocidad - 1.0) * 100:.0f}%",
            volume=f"{'+' if intensidad >= 1.0 else ''}{(intensidad - 1.0) * 100:.0f}%",
        )

        # Generate and save the preview
        await communicator.save(preview_file)

        return preview_file, "Vista previa generada"

    except Exception as e:
        return None, f"Error en vista previa: {str(e)}"


def actualizar_favoritos_html(config=None):
    if config is None:
        config = load_config()

    html = "<div style='max-height: 200px; overflow-y: auto; padding: 8px;'>"
    for i, fav in enumerate(config.get("favorites", [])[:5]):
        html += f"""
        <div style='padding: 8px; margin-bottom: 5px; border-radius: 4px; 
                  background-color: {"#f0f7ff" if i % 2 == 0 else "#e6f3ff"}; 
                  display: flex; justify-content: space-between; align-items: center'>
            <div style='font-weight: {"bold" if fav == config.get("last_voice") else "normal"}'>{fav}</div>
        </div>"""

    if not config.get("favorites", []):
        html += "<div style='text-align: center; color: #666;'>No hay favoritos</div>"

    return html + "</div>"


def actualizar_presets_html(config=None):
    if config is None:
        config = load_config()

    presets = config.get("saved_presets", {})

    html = "<div style='max-height: 200px; overflow-y: auto; padding: 8px;'>"
    if presets:
        for name, settings in presets.items():
            html += f"""
            <div style='padding: 8px; margin-bottom: 8px; border-radius: 4px; 
                      background-color: #f0f7ff; border: 1px solid #cce0ff;'
                      onclick="selectPreset('{name}')" style="cursor:pointer">
                <div style='font-weight: bold; margin-bottom: 4px;'>{name}</div>
                <div style='font-size: 0.9em; color: #444;'>
                    <span style='margin-right: 10px;'>Voz: {settings.get('voice', 'N/A')}</span><br>
                    <span style='margin-right: 10px;'>Velocidad: {settings.get('speed', 1.0)}</span> | 
                    <span style='margin-right: 10px;'>Volumen: {settings.get('volume', 1.0)}</span> | 
                    <span>Tono: {settings.get('pitch', 0.0)}</span>
                    {f"<br><span>Estilo: {settings.get('style', 'General')}</span>" if 'style' in settings else ""}
                </div>
            </div>"""
    else:
        html += "<div style='text-align: center; color: #666;'>No hay configuraciones guardadas</div>"

    return html + "</div>"


def guardar_preset(nombre, voz, velocidad, intensidad, tono, clarity, estilo, formato):
    if not nombre or nombre.strip() == "":
        return (
            "Error: Debes proporcionar un nombre para la configuración",
            actualizar_presets_html(),
        )

    config = load_config()

    # Create the preset structure if it doesn't exist
    if "saved_presets" not in config:
        config["saved_presets"] = {}

    # Save the preset
    config["saved_presets"][nombre.strip()] = {
        "voice": voz,
        "speed": float(velocidad),
        "volume": float(intensidad),
        "pitch": float(tono),
        "clarity": clarity,
        "style": estilo,
        "format": formato,
    }

    save_config(config)
    return (
        f"✅ Configuración '{nombre}' guardada correctamente",
        actualizar_presets_html(config),
    )


def cargar_preset(preset_name):
    config = load_config()
    presets = config.get("saved_presets", {})

    if preset_name not in presets:
        return (
            gr.update(),  # voz
            gr.update(),  # velocidad
            gr.update(),  # intensidad
            gr.update(),  # tono
            gr.update(),  # clarity
            gr.update(),  # estilo_voz
            gr.update(),  # formato
            f"❌ La configuración '{preset_name}' no existe",
        )

    preset = presets[preset_name]

    return (
        gr.update(value=preset.get("voice", "")),  # voz
        gr.update(value=preset.get("speed", 1.0)),  # velocidad
        gr.update(value=preset.get("volume", 1.0)),  # intensidad
        gr.update(value=preset.get("pitch", 0.0)),  # tono
        gr.update(value=preset.get("clarity", 0)),  # clarity
        gr.update(value=preset.get("style", "General")),  # estilo_voz
        gr.update(value=preset.get("format", "mp3")),  # formato
        f"✅ Configuración '{preset_name}' cargada",  # status_msg
    )


async def get_voice_styles(voice_name):
    try:
        # Common styles that would be implemented via SSML
        common_styles = ["General", "Calm", "Cheerful", "Sad", "Angry", "Excited"]
        return common_styles
    except Exception as e:
        print(f"Error al obtener estilos: {e}")
        return ["General"]


def crear_interfaz():
    # Load configuration
    config = load_config()
    last_settings = config.get(
        "last_settings",
        {"speed": 1.0, "volume": 1.0, "pitch": 0.0, "clarity": 0, "style": "General"},
    )

    # Create a new event loop for initialization
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    # Get initial voice list
    spanish_voices = loop.run_until_complete(get_spanish_voices())
    voice_options = [v["ShortName"] for v in spanish_voices]

    # Prepare gender filter lists
    female_voices = [
        v["ShortName"] for v in loop.run_until_complete(get_spanish_voices("Female"))
    ]
    male_voices = [
        v["ShortName"] for v in loop.run_until_complete(get_spanish_voices("Male"))
    ]

    # Initialize with saved voice
    voice_styles = loop.run_until_complete(
        get_voice_styles(config.get("last_voice", "es-MX-DaliaNeural"))
    )

    with gr.Blocks(title="Generador de Sermones", theme=gr.themes.Soft()) as interfaz:
        gr.Markdown(
            """
            # 🎤 Generador de audios Automático
            
            Convierte texto a voz con diferentes acentos españoles y ajustes personalizados.
            """
        )

        with gr.Row():
            with gr.Column(scale=3):
                texto = gr.Textbox(
                    label="Texto del sermón",
                    lines=8,
                    placeholder="Escribe tu sermón aquí...",
                    autofocus=True,
                )

                with gr.Row():
                    with gr.Column(scale=1):
                        filtro_genero = gr.Radio(
                            ["Todos", "Hombre", "Mujer"],
                            label="Filtro de voces",
                            value="Todos",
                            info="Filtra las voces por género",
                        )

                    with gr.Column(scale=2):
                        voz = gr.Dropdown(
                            label="Voz",
                            choices=voice_options,
                            value=(
                                config.get("last_voice", "")
                                if config.get("last_voice", "") in voice_options
                                else None
                            ),
                            interactive=True,
                            info="Selecciona el dialecto español y voz a utilizar",
                        )

                with gr.Row():
                    formato = gr.Dropdown(
                        label="Formato",
                        choices=AUDIO_FORMATS,
                        value=config.get("audio_format", DEFAULT_FORMAT),
                        interactive=True,
                        info="Formato del archivo de audio",
                    )

                    estilo_voz = gr.Dropdown(
                        label="Estilo de voz",
                        choices=voice_styles,
                        value=last_settings.get("style", "General"),
                        interactive=True,
                        info="Estilo emocional de la voz",
                    )

                with gr.Group():
                    gr.Markdown("### ⚙️ Ajustes de audio")
                    with gr.Row():
                        velocidad = gr.Slider(
                            minimum=0.5,
                            maximum=2.0,
                            value=last_settings.get("speed", 1.0),
                            step=0.05,
                            label="Velocidad",
                            info="Controla la rapidez de la voz",
                        )
                        intensidad = gr.Slider(
                            minimum=0.5,
                            maximum=1.5,
                            value=last_settings.get("volume", 1.0),
                            step=0.05,
                            label="Volumen",
                            info="Ajusta la intensidad del audio",
                        )

                    with gr.Row():
                        tono = gr.Slider(
                            minimum=-1.0,
                            maximum=1.0,
                            value=last_settings.get("pitch", 0.0),
                            step=0.1,
                            label="Tono",
                            info="Modifica el tono de la voz (± 50Hz)",
                        )

                        clarity = gr.Slider(
                            minimum=-5,
                            maximum=5,
                            value=last_settings.get("clarity", 0),
                            step=1,
                            label="Claridad",
                            info="Ajusta la claridad de la pronunciación",
                        )

                with gr.Row():
                    boton = gr.Button("🎙️ Generar", variant="primary", size="lg")
                    play_btn = gr.Button("▶️ Reproducir", interactive=False)
                    preview_btn = gr.Button("👂 Vista Previa", size="sm")

                with gr.Row():
                    with gr.Column():
                        nombre_preset = gr.Textbox(
                            label="Nombre de configuración",
                            placeholder="Mi configuración personalizada",
                        )
                    with gr.Column():
                        guardar_btn = gr.Button("💾 Guardar configuración")

                status_msg = gr.Markdown("Esperando para generar audio...")

            with gr.Column(scale=2):
                # Preview audio at the top
                gr.Markdown("### 🔊 Vista Previa")
                preview_audio = gr.Audio(
                    label="",
                    type="filepath",
                    elem_id="preview_player",
                    interactive=False,
                    show_download_button=False,
                    visible=True,
                )

                # Main audio player
                gr.Markdown("### 🎧 Sermón Completo")
                audio = gr.Audio(
                    label="",
                    type="filepath",
                    elem_id="audio_player",
                    interactive=True,
                    show_download_button=True,
                    visible=True,
                )

                archivo = gr.File(
                    label="Descargar archivo",
                    visible=False,
                    elem_id="audio_download",
                )

                with gr.Tabs():
                    with gr.TabItem("📚 Audios Generados"):
                        audio_list = gr.HTML(get_audio_list_html())
                        refresh_btn = gr.Button(
                            "🔄 Actualizar lista", variant="secondary", size="sm"
                        )

                    with gr.TabItem("💚 Voces favoritas"):
                        favoritos = gr.HTML(actualizar_favoritos_html())

                    with gr.TabItem("⚙️ Configuraciones guardadas"):
                        presets = gr.HTML(actualizar_presets_html())
                        with gr.Row():
                            preset_dropdown = gr.Dropdown(
                                label="Seleccionar configuración",
                                choices=list(config.get("saved_presets", {}).keys()),
                                interactive=True,
                            )
                            cargar_btn = gr.Button("📂 Cargar")

                with gr.Accordion("ℹ️ Ayuda", open=False):
                    gr.Markdown(
                        """
                    ### Cómo usar el generador de sermones
                    
                    1. Escribe o pega el texto del sermón
                    2. Selecciona la voz deseada (puedes filtrar por hombre o mujer)
                    3. Ajusta los parámetros de audio (velocidad, volumen, tono, claridad y estilo)
                    4. Haz clic en "Vista Previa" para escuchar un fragmento corto
                    5. Cuando estés satisfecho, haz clic en "Generar Sermón"
                    6. Revisa tus audios anteriores en la pestaña "Audios Generados"
                    
                    ### Guardar y cargar configuraciones
                    
                    1. Establece los parámetros deseados (voz, velocidad, volumen, etc.)
                    2. Escribe un nombre para tu configuración y haz clic en "Guardar"
                    3. Para volver a usar esta configuración, selecciónala del menú desplegable y haz clic en "Cargar"
                    
                    Las configuraciones y voces favoritas se guardan automáticamente.
                    """
                    )

        # Filter voices by gender
        def filter_voices(gender):
            if gender == "Hombre":
                return gr.update(choices=male_voices)
            elif gender == "Mujer":
                return gr.update(choices=female_voices)
            else:
                return gr.update(choices=voice_options)

        filtro_genero.change(fn=filter_voices, inputs=[filtro_genero], outputs=[voz])

        def update_styles(voice):
            return loop.run_until_complete(get_voice_styles(voice))

        voz.change(fn=update_styles, inputs=[voz], outputs=[estilo_voz])

        # Update audio list function
        def actualizar_lista_audios():
            return get_audio_list_html()

        # Refresh audio list
        refresh_btn.click(fn=actualizar_lista_audios, outputs=[audio_list])

        # Wrapper functions for async operations
        def wrapper_generar_audio(
            texto, voz, velocidad, intensidad, tono, clarity, estilo, formato
        ):
            return loop.run_until_complete(
                generar_audio(
                    texto, voz, velocidad, intensidad, tono, clarity, estilo, formato
                )
            )

        def wrapper_generar_preview(
            texto, voz, velocidad, intensidad, tono, clarity, estilo
        ):
            return loop.run_until_complete(
                generar_preview(
                    texto, voz, velocidad, intensidad, tono, clarity, estilo
                )
            )

        # Generate audio event with fixed async handling
        boton.click(
            fn=wrapper_generar_audio,
            inputs=[
                texto,
                voz,
                velocidad,
                intensidad,
                tono,
                clarity,
                estilo_voz,
                formato,
            ],
            outputs=[
                audio,
                archivo,
                favoritos,
                presets,
                audio_list,
                status_msg,
                play_btn,
                preview_audio,
            ],
        )

        # Generate preview with fixed async handling
        preview_btn.click(
            fn=wrapper_generar_preview,
            inputs=[texto, voz, velocidad, intensidad, tono, clarity, estilo_voz],
            outputs=[preview_audio, status_msg],
        )

        # Play audio event
        play_btn.click(fn=play_audio_file, inputs=[audio], outputs=[status_msg])

        # Save preset event
        guardar_btn.click(
            fn=guardar_preset,
            inputs=[
                nombre_preset,
                voz,
                velocidad,
                intensidad,
                tono,
                clarity,
                estilo_voz,
                formato,
            ],
            outputs=[status_msg, presets],
        )

        # Update preset list
        def update_preset_list():
            config = load_config()
            return gr.update(choices=list(config.get("saved_presets", {}).keys()))

        guardar_btn.click(fn=update_preset_list, outputs=[preset_dropdown])

        # Load preset event
        cargar_btn.click(
            fn=cargar_preset,
            inputs=[preset_dropdown],
            outputs=[
                voz,
                velocidad,
                intensidad,
                tono,
                clarity,
                estilo_voz,
                formato,
                status_msg,
            ],
        )

    return interfaz


if __name__ == "__main__":
    # Run the interface
    app = crear_interfaz()
    app.launch(server_port=7860, share=False, show_error=True, debug=True)

import discord
from discord.ext import commands, tasks
import sqlite3
import time
import os
from datetime import datetime, timedelta
import threading
from flask import Flask
import libsql_experimental as libsql

# ---------------- KEEP ALIVE ----------------

app = Flask('')

@app.route('/')
def home():
    return "Bot activo"

def run():
    app.run(host='0.0.0.0', port=8080)

def keep_alive():
    t = threading.Thread(target=run)
    t.start()

keep_alive()

# ---------------- TOKENS ----------------

TOKEN       = os.environ["DISCORD_TOKEN"]
TURSO_URL   = os.environ["TURSO_URL"]
TURSO_TOKEN = os.environ["TURSO_TOKEN"]

# ---------------- CANALES ----------------

CANAL_REGISTRO  = 1482912693680869426
CANAL_AVISOS    = 1482912285230895205
CANAL_DASHBOARD = 1482912464483127336

# ---------------- GIFs ----------------

GIF_PANEL  = "https://i.imgur.com/C8IaPT6.gif"
GIF_AVISO  = "https://i.imgur.com/C8IaPT6.gif"
GIF_ONLINE = "https://i.imgur.com/C8IaPT6.gif"

# ---------------- BOT INFO ----------------

BOT_NAME = "KittyTimer"
BOT_ICON = "https://i.imgur.com/3b7Kjh8.png"

# ---------------- COLORES E ICONOS ----------------

COLORES = {
    "Cajas":      0x3498db,
    "Robo":       0xe74c3c,
    "Capataz":    0x2ecc71,
    "Cargas":     0x95a5a6,
    "Plantas":    0x1abc9c,
    "Planos x6":  0x9b59b6,
    "Planos x8":  0xbdc3c7,
    "Planos x10": 0xf1c40f,
    "Ganzuas":    0xe67e22,
    "Test":       0xff6b6b,
}

ICONOS = {
    "Cajas":      "📦",
    "Robo":       "💰",
    "Capataz":    "👷",
    "Cargas":     "🔫",
    "Plantas":    "🌿",
    "Planos x6":  "🟣",
    "Planos x8":  "⬜",
    "Planos x10": "🟡",
    "Ganzuas":    "🗝️",
    "Test":       "🧪",
}

# ---------------- DISCORD ----------------

intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)

# ================================================================
# DATABASE — estrategia dual:
# - sqlite3 local para todas las lecturas/escrituras (rápido, confiable)
# - libsql sync en background para persistir en Turso (sobrevive reinicios)
# ================================================================

# 1) Conexión Turso — sincroniza la DB local con la nube
turso = libsql.connect("timers.db", sync_url=TURSO_URL, auth_token=TURSO_TOKEN)
try:
    turso.sync()  # baja datos de Turso al archivo local timers.db
except Exception as e:
    print(f"[TURSO] sync inicial falló: {e}")

# 2) Conexión sqlite3 local — se usa para TODAS las queries
con = sqlite3.connect("timers.db", check_same_thread=False)
cur = con.cursor()

# Crear tablas si no existen
cur.executescript("""
CREATE TABLE IF NOT EXISTS timers(
    user_id  INTEGER,
    username TEXT,
    tipo     TEXT,
    numero   INTEGER,
    inicio   INTEGER,
    fin      INTEGER,
    mensaje  INTEGER
);
CREATE TABLE IF NOT EXISTS ranking(
    user_id  INTEGER,
    username TEXT,
    tipo     TEXT,
    cantidad INTEGER
);
CREATE TABLE IF NOT EXISTS dashboard(
    msg_id INTEGER
);
""")
con.commit()

def db_write(sql, params=()):
    """Escribe localmente y sincroniza con Turso en un hilo aparte."""
    cur.execute(sql, params)
    con.commit()
    def _push():
        try:
            turso.sync()
        except Exception as e:
            print(f"[TURSO] push falló: {e}")
    threading.Thread(target=_push, daemon=True).start()

def db_read(sql, params=()):
    cur.execute(sql, params)
    return cur.fetchall()

def db_readone(sql, params=()):
    cur.execute(sql, params)
    return cur.fetchone()

# ---------------- TIEMPO ----------------

def now():
    return int(time.time())

def hora_arg(ts):
    return (datetime.utcfromtimestamp(ts) - timedelta(hours=3)).strftime("%H:%M")

def hora_hub(ts):
    return datetime.utcfromtimestamp(ts).strftime("%H:%M")

def tiempo_restante(seg):
    h = int(seg) // 3600
    m = (int(seg) % 3600) // 60
    return f"{h}h {m}m" if h > 0 else f"{m}m"

# ---------------- BARRA ----------------

def barra(inicio, fin):
    total    = fin - inicio
    progreso = max(0, min(now() - inicio, total))
    pct      = progreso / total if total > 0 else 1
    llenos   = int(14 * pct)
    bar      = "▰" * llenos + "▱" * (14 - llenos)
    restante = max(0, fin - now())
    return f"{bar} **{int(pct * 100)}%**\n⚡ Restante: `{tiempo_restante(restante)}`"

# ---------------- FOOTER ----------------

def add_footer(embed):
    embed.set_footer(text="KittyTimer", icon_url=BOT_ICON)
    embed.set_thumbnail(url=BOT_ICON)
    embed.timestamp = datetime.utcnow()
    return embed

# ---------------- RANKING ----------------

def sumar_ranking(user_id, username, tipo):
    row = db_readone(
        "SELECT cantidad FROM ranking WHERE user_id=? AND tipo=?",
        (user_id, tipo)
    )
    if row:
        db_write("UPDATE ranking SET cantidad=cantidad+1 WHERE user_id=? AND tipo=?", (user_id, tipo))
    else:
        db_write("INSERT INTO ranking VALUES (?,?,?,1)", (user_id, username, tipo))

# ---------------- TIMER ----------------

async def iniciar_timer_raw(user, tipo, horas):
    row    = db_readone("SELECT MAX(numero) FROM timers WHERE user_id=? AND tipo=?", (user.id, tipo))
    numero = 1 if (row is None or row[0] is None) else row[0] + 1

    inicio = now()
    fin    = inicio + round(horas * 3600)
    color  = COLORES.get(tipo, 0x00ffaa)
    icono  = ICONOS.get(tipo, "⏱")

    embed = discord.Embed(title=f"{icono} {tipo} #{numero}", color=color)
    embed.add_field(name="👤 Usuario",  value=user.mention,        inline=True)
    embed.add_field(name="⏳ Duración", value=f"`{int(horas)}h`",   inline=True)
    embed.add_field(name="\u200b",      value="\u200b",             inline=True)
    embed.add_field(name="📊 Progreso", value=barra(inicio, fin),   inline=False)
    embed.add_field(name="🕐 Fin ARG",  value=f"`{hora_arg(fin)}`", inline=True)
    embed.add_field(name="🌐 Fin HUB",  value=f"`{hora_hub(fin)}`", inline=True)
    embed.add_field(name="📅 Finaliza", value=f"<t:{fin}:R>",       inline=True)
    add_footer(embed)

    canal = bot.get_channel(CANAL_REGISTRO)
    msg   = await canal.send(embed=embed)

    db_write(
        "INSERT INTO timers VALUES (?,?,?,?,?,?,?)",
        (user.id, user.display_name, tipo, numero, inicio, fin, msg.id)
    )
    sumar_ranking(user.id, user.display_name, tipo)

async def iniciar_timer(ctx, tipo, horas):
    await iniciar_timer_raw(ctx.author, tipo, horas)

# ---------------- COMANDOS ----------------

@bot.command()
async def cajas(ctx):
    await iniciar_timer(ctx, "Cajas", 3)

@bot.command()
async def robo(ctx):
    await iniciar_timer(ctx, "Robo", 2)

@bot.command()
async def capataz(ctx):
    await iniciar_timer(ctx, "Capataz", 6)

@bot.command()
async def cargas(ctx):
    await iniciar_timer(ctx, "Cargas", 72)

@bot.command()
async def plantas(ctx):
    await iniciar_timer(ctx, "Plantas", 3)

@bot.command()
async def planos6(ctx):
    await iniciar_timer(ctx, "Planos x6", 6)

@bot.command()
async def planos8(ctx):
    await iniciar_timer(ctx, "Planos x8", 8)

@bot.command()
async def planos10(ctx):
    await iniciar_timer(ctx, "Planos x10", 10)

@bot.command()
async def test(ctx):
    await iniciar_timer(ctx, "Test", 0.02)

@bot.command()
async def ganzuas(ctx):
    await iniciar_timer(ctx, "Ganzuas", 192)

# ---------------- RESET ----------------

@bot.command()
async def resettimers(ctx):
    global dashboard_msg

    embed_working = discord.Embed(
        title="⏳ Reiniciando base de datos...",
        description="Borrando todos los timers. Aguardá un momento.",
        color=0xf39c12
    )
    add_footer(embed_working)
    msg = await ctx.send(embed=embed_working)

    db_write("DELETE FROM timers")
    db_write("DELETE FROM dashboard")
    dashboard_msg = None

    try:
        turso.sync()
        descripcion = "✅ Todos los timers fueron eliminados correctamente."
        color = 0x2ecc71
    except Exception as e:
        descripcion = f"⚠️ Timers borrados localmente pero el sync con Turso falló: `{e}`\nSe sincronizará automáticamente."
        color = 0xe67e22

    embed_done = discord.Embed(title="🧹 Base de datos reiniciada", description=descripcion, color=color)
    add_footer(embed_done)
    await msg.edit(embed=embed_done)

# ---------------- AYUDA ----------------

@bot.command()
async def ayuda(ctx):
    embed = discord.Embed(
        title="📖 Comandos — KittyTimer",
        description="Todo lo que podés hacer con el bot.",
        color=0x5865F2
    )
    embed.add_field(name="🎮 Panel", value="`!panel` — Panel con botones para iniciar timers", inline=False)
    embed.add_field(
        name="⏱ Timers",
        value=(
            "`!cajas` 📦 3h · `!robo` 💰 2h · `!capataz` 👷 6h · `!cargas` 🔫 72h\n"
            "`!plantas` 🌿 3h · `!planos6` 🟣 6h · `!planos8` ⬜ 8h · `!planos10` 🟡 10h\n"
            "`!ganzuas` 🗝️ 8 días"
        ),
        inline=False
    )
    embed.add_field(
        name="📋 Gestión",
        value="`!mistimers` — Tus timers activos\n`!stats` — Tus estadísticas\n`!farmeritos` — Ranking general",
        inline=False
    )
    add_footer(embed)
    await ctx.send(embed=embed)

# ---------------- VER MIS TIMERS ----------------

class CancelarView(discord.ui.View):

    def __init__(self, user_id, tipo, numero):
        super().__init__(timeout=None)
        self.user_id = user_id
        self.tipo    = tipo
        self.numero  = numero

    @discord.ui.button(label="❌ Cancelar", style=discord.ButtonStyle.danger)
    async def cancelar(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("No podés cancelar timers de otro usuario.", ephemeral=True)
            return
        db_write(
            "DELETE FROM timers WHERE user_id=? AND tipo=? AND numero=?",
            (self.user_id, self.tipo, self.numero)
        )
        embed = discord.Embed(description="🛑 Timer cancelado.", color=0xe74c3c)
        add_footer(embed)
        await interaction.response.edit_message(embed=embed, view=None)

@bot.command()
async def mistimers(ctx):
    timers = db_read("SELECT * FROM timers WHERE user_id=?", (ctx.author.id,))

    if not timers:
        embed = discord.Embed(description="✅ No tenés timers activos.", color=0x2ecc71)
        add_footer(embed)
        await ctx.send(embed=embed)
        return

    for t in timers:
        color = COLORES.get(t[2], 0x3498db)
        icono = ICONOS.get(t[2], "⏱")
        embed = discord.Embed(title=f"{icono} {t[2]} #{t[3]}", color=color)
        embed.add_field(name="📊 Progreso", value=barra(t[4], t[5]),     inline=False)
        embed.add_field(name="🕐 Fin ARG",  value=f"`{hora_arg(t[5])}`", inline=True)
        embed.add_field(name="🌐 Fin HUB",  value=f"`{hora_hub(t[5])}`", inline=True)
        embed.add_field(name="📅 Finaliza", value=f"<t:{t[5]}:R>",       inline=True)
        add_footer(embed)
        await ctx.send(embed=embed, view=CancelarView(ctx.author.id, t[2], t[3]))

# ---------------- PANEL ----------------

class Panel(discord.ui.View):

    # Fila 1 — Farm principal (azul, rojo, verde, azul)
    @discord.ui.button(label="📦 Cajas",      style=discord.ButtonStyle.primary,   row=0)
    async def cajas(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer(ephemeral=True)
        await iniciar_timer_raw(interaction.user, "Cajas", 3)

    @discord.ui.button(label="💰 Robo",       style=discord.ButtonStyle.danger,    row=0)
    async def robo(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer(ephemeral=True)
        await iniciar_timer_raw(interaction.user, "Robo", 2)

    @discord.ui.button(label="👷 Capataz",    style=discord.ButtonStyle.success,   row=0)
    async def capataz(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer(ephemeral=True)
        await iniciar_timer_raw(interaction.user, "Capataz", 6)

    @discord.ui.button(label="🔫 Cargas",     style=discord.ButtonStyle.primary,   row=0)
    async def cargas(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer(ephemeral=True)
        await iniciar_timer_raw(interaction.user, "Cargas", 72)

    # Fila 2 — Plantas, Planos y Ganzúas (verde, gris, rojo, azul, gris)
    @discord.ui.button(label="🌿 Plantas",    style=discord.ButtonStyle.success,   row=1)
    async def plantas(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer(ephemeral=True)
        await iniciar_timer_raw(interaction.user, "Plantas", 3)

    @discord.ui.button(label="🟣 Planos x6",  style=discord.ButtonStyle.secondary, row=1)
    async def planos6(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer(ephemeral=True)
        await iniciar_timer_raw(interaction.user, "Planos x6", 6)

    @discord.ui.button(label="⬜ Planos x8",  style=discord.ButtonStyle.secondary, row=1)
    async def planos8(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer(ephemeral=True)
        await iniciar_timer_raw(interaction.user, "Planos x8", 8)

    @discord.ui.button(label="🟡 Planos x10", style=discord.ButtonStyle.secondary, row=1)
    async def planos10(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer(ephemeral=True)
        await iniciar_timer_raw(interaction.user, "Planos x10", 10)

    # Fila 3 — Ganzúas solo
    @discord.ui.button(label="🗝️ Ganzúas · 8d", style=discord.ButtonStyle.danger, row=2)
    async def ganzuas(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer(ephemeral=True)
        await iniciar_timer_raw(interaction.user, "Ganzuas", 192)

@bot.command()
async def panel(ctx):
    embed = discord.Embed(
        title="🎮 Panel de Timers — KittyTimer",
        description=(
            "Usá los botones para iniciar tu timer.\n\n"
            "**🏭 Farm Principal**\n"
            "📦 Cajas `3h`  ·  💰 Robo `2h`  ·  👷 Capataz `6h`  ·  🔫 Cargas `72h`\n\n"
            "**🌱 Plantas & Planos**\n"
            "🌿 Plantas `3h`  ·  🟣 Planos x6 `6h`  ·  ⬜ Planos x8 `8h`  ·  🟡 Planos x10 `10h`\n\n"
            "**🗝️ Especial**\n"
            "Ganzúas `8 días`\n\n"
            "Usá `!ayuda` para ver todos los comandos."
        ),
        color=0x5865F2
    )
    embed.set_image(url=GIF_PANEL)
    add_footer(embed)
    await ctx.send(embed=embed, view=Panel())

# ---------------- ACTUALIZAR BARRAS ----------------

@tasks.loop(seconds=10)
async def actualizar_barras():
    timers = db_read("SELECT * FROM timers")
    canal  = bot.get_channel(CANAL_REGISTRO)
    if canal is None:
        return

    for t in timers:
        inicio, fin = t[4], t[5]
        color = COLORES.get(t[2], 0x00ffaa)
        icono = ICONOS.get(t[2], "⏱")

        embed = discord.Embed(title=f"{icono} {t[2]} #{t[3]}", color=color)
        embed.add_field(name="👤 Usuario",        value=f"<@{t[0]}>",                        inline=True)
        embed.add_field(name="⏳ Duración total", value=f"`{tiempo_restante(fin - inicio)}`", inline=True)
        embed.add_field(name="\u200b",            value="\u200b",                             inline=True)

        if now() >= fin:
            embed.add_field(name="📊 Progreso", value="▰" * 14 + " **100%**\n✅ `Finalizado`", inline=False)
        else:
            embed.add_field(name="📊 Progreso", value=barra(inicio, fin), inline=False)

        embed.add_field(name="🕐 Fin ARG", value=f"`{hora_arg(fin)}`", inline=True)
        embed.add_field(name="🌐 Fin HUB", value=f"`{hora_hub(fin)}`", inline=True)
        embed.add_field(name="📅 Finaliza", value=f"<t:{fin}:R>",      inline=True)
        add_footer(embed)

        try:
            msg = await canal.fetch_message(t[6])
            await msg.edit(embed=embed)
        except:
            pass

# ---------------- DASHBOARD ----------------

dashboard_msg = None

async def cargar_dashboard_msg():
    global dashboard_msg
    canal = bot.get_channel(CANAL_DASHBOARD)
    if canal is None:
        return
    row = db_readone("SELECT msg_id FROM dashboard")
    if row:
        try:
            dashboard_msg = await canal.fetch_message(row[0])
        except:
            db_write("DELETE FROM dashboard")
            dashboard_msg = None

def build_dashboard_embed():
    timers = db_read("SELECT * FROM timers")
    timers = sorted(timers, key=lambda x: x[5])
    texto  = ""

    for t in timers:
        restante = t[5] - now()
        if restante <= 0:
            continue
        icono  = ICONOS.get(t[2], "⏱")
        texto += f"**{icono} {t[2]} #{t[3]}** — <@{t[0]}>\n"
        texto += f"{barra(t[4], t[5])}\n"
        texto += f"🕐 `{hora_arg(t[5])}` · 🌐 `{hora_hub(t[5])}` · <t:{t[5]}:R>\n"
        texto += "─────────────────────\n"

    embed = discord.Embed(
        title="📊 Dashboard — KittyTimer",
        description=texto or "✅ No hay timers activos en este momento.",
        color=0x5865F2
    )
    add_footer(embed)
    return embed

@tasks.loop(seconds=10)
async def dashboard():
    global dashboard_msg
    canal = bot.get_channel(CANAL_DASHBOARD)
    if canal is None:
        return

    embed = build_dashboard_embed()

    if dashboard_msg is None:
        dashboard_msg = await canal.send(embed=embed)
        db_write("DELETE FROM dashboard")
        db_write("INSERT INTO dashboard VALUES (?)", (dashboard_msg.id,))
    else:
        try:
            await dashboard_msg.edit(embed=embed)
        except discord.NotFound:
            db_write("DELETE FROM dashboard")
            dashboard_msg = None
        except Exception:
            pass

# ---------------- FINALIZAR ----------------

@tasks.loop(seconds=10)
async def finalizar():
    lista = db_read("SELECT * FROM timers WHERE fin <= ?", (now(),))
    canal = bot.get_channel(CANAL_AVISOS)
    if canal is None:
        return

    for t in lista:
        try:
            user    = await bot.fetch_user(t[0])
            mention = user.mention
        except:
            mention = f"<@{t[0]}>"

        icono = ICONOS.get(t[2], "⏱")
        color = COLORES.get(t[2], 0x00ff00)

        embed = discord.Embed(
            title="✅ ¡Timer terminado!",
            description=f"{mention} terminó **{icono} {t[2]} #{t[3]}**\n\n¡Ya podés volver a iniciarlo!",
            color=color
        )
        embed.set_image(url=GIF_AVISO)
        add_footer(embed)

        await canal.send(embed=embed)
        db_write("DELETE FROM timers WHERE mensaje=?", (t[6],))

# ---------------- STATS ----------------

@bot.command()
async def stats(ctx):
    datos = db_read("SELECT tipo,cantidad FROM ranking WHERE user_id=?", (ctx.author.id,))
    embed = discord.Embed(title=f"📊 Estadísticas de {ctx.author.display_name}", color=0x3498db)
    embed.set_thumbnail(url=ctx.author.display_avatar.url)
    embed.set_footer(text="KittyTimer", icon_url=BOT_ICON)
    embed.timestamp = datetime.utcnow()

    if not datos:
        embed.description = "Todavía no iniciaste ningún timer."
    else:
        total = sum(c for _, c in datos)
        for tipo, cant in sorted(datos, key=lambda x: x[1], reverse=True):
            embed.add_field(name=f"{ICONOS.get(tipo,'⏱')} {tipo}", value=f"`{cant}` veces", inline=True)
        embed.set_footer(text=f"{BOT_NAME} • Total: {total} timers iniciados", icon_url=BOT_ICON)

    await ctx.send(embed=embed)

# ---------------- RANKING ----------------

@bot.command()
async def farmeritos(ctx):
    embed  = discord.Embed(title="🏆 Farmeritos Vividos", description="Top 5 por categoría", color=0xf1c40f)
    medals = ["🥇", "🥈", "🥉", "4️⃣", "5️⃣"]

    for tipo in ["Cajas", "Robo", "Capataz", "Cargas", "Plantas", "Planos x6", "Planos x8", "Planos x10", "Ganzuas"]:
        top   = db_read("SELECT username,cantidad FROM ranking WHERE tipo=? ORDER BY cantidad DESC LIMIT 5", (tipo,))
        texto = "".join(f"{medals[i]} **{u}** — `{c}`\n" for i, (u, c) in enumerate(top)) or "*Sin datos aún*"
        embed.add_field(name=f"{ICONOS.get(tipo,'⏱')} {tipo}", value=texto, inline=True)

    add_footer(embed)
    await ctx.send(embed=embed)

# ---------------- READY ----------------

@bot.event
async def on_ready():
    print(f"✅ {bot.user} conectado y listo.")
    await cargar_dashboard_msg()
    dashboard.start()
    finalizar.start()
    actualizar_barras.start()

    canal = bot.get_channel(CANAL_REGISTRO)
    if canal:
        embed = discord.Embed(
            title="🟢 KittyTimer Online",
            description="El bot se conectó correctamente y está listo.\nUsá `!panel` para abrir el panel de timers.",
            color=0x2ecc71
        )
        embed.set_image(url=GIF_ONLINE)
        add_footer(embed)
        await canal.send(embed=embed)

bot.run(TOKEN)

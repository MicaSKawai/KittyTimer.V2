import discord
from discord.ext import commands, tasks
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

CANAL_REGISTRO  = 1482912693680869426   # timers + mensajes del bot
CANAL_AVISOS    = 1482912285230895205   # SOLO avisos de timer terminado
CANAL_DASHBOARD = 1482912464483127336   # dashboard

# ---------------- GIFs ----------------

GIF_PANEL  = "https://i.imgur.com/C8IaPT6.gif"
GIF_AVISO  = "https://i.imgur.com/C8IaPT6.gif"
GIF_ONLINE = "https://i.imgur.com/C8IaPT6.gif"

# ---------------- BOT INFO ----------------

BOT_NAME = "KittyTimer"
BOT_ICON = "https://i.imgur.com/4M34hi2.png"

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
    "Test":       "🧪",
}

# ---------------- DISCORD ----------------

intents = discord.Intents.default()
intents.message_content = True

bot = commands.Bot(command_prefix="!", intents=intents)

# ---------------- DATABASE (TURSO) ----------------
# Usamos sync_url para replicación — cada write hace commit+sync
# para garantizar que los datos queden en la nube inmediatamente

db = libsql.connect("timers.db", sync_url=TURSO_URL, auth_token=TURSO_TOKEN)
db.sync()

for sql in [
    """CREATE TABLE IF NOT EXISTS timers(
        user_id INTEGER,
        username TEXT,
        tipo TEXT,
        numero INTEGER,
        inicio INTEGER,
        fin INTEGER,
        mensaje INTEGER
    )""",
    """CREATE TABLE IF NOT EXISTS ranking(
        user_id INTEGER,
        username TEXT,
        tipo TEXT,
        cantidad INTEGER
    )""",
    """CREATE TABLE IF NOT EXISTS dashboard(
        msg_id INTEGER
    )""",
]:
    db.execute(sql)

db.commit()
db.sync()

def query(sql, params=()):
    """Lee de la DB — hace sync primero para tener datos frescos."""
    db.sync()
    return db.execute(sql, params)

def execute(sql, params=()):
    """Escribe en la DB — hace commit+sync para persistir en Turso."""
    db.execute(sql, params)
    db.commit()
    db.sync()

# ---------------- TIEMPO ----------------

def now():
    return int(time.time())

def hora_arg(ts):
    utc = datetime.utcfromtimestamp(ts)
    return (utc - timedelta(hours=3)).strftime("%H:%M")

def hora_hub(ts):
    utc = datetime.utcfromtimestamp(ts)
    return (utc - timedelta(hours=3) + timedelta(hours=3)).strftime("%H:%M")

def tiempo_restante(seg):
    h = seg // 3600
    m = (seg % 3600) // 60
    return f"{h}h {m}m" if h > 0 else f"{m}m"

# ---------------- BARRA ----------------

def barra(inicio, fin):
    total    = fin - inicio
    progreso = max(0, min(now() - inicio, total))
    pct      = progreso / total if total > 0 else 1
    llenos   = int(14 * pct)
    bar      = "▰" * llenos + "▱" * (14 - llenos)
    restante = max(0, fin - now())
    return f"{bar} **{int(pct*100)}%**\n⚡ Restante: `{tiempo_restante(restante)}`"

# ---------------- FOOTER ----------------

def add_footer(embed):
    embed.set_footer(text=f"{BOT_NAME} • Timer Bot", icon_url=BOT_ICON)
    embed.timestamp = datetime.utcnow()
    return embed

# ---------------- RANKING ----------------

def sumar_ranking(user_id, username, tipo):
    row = query("SELECT cantidad FROM ranking WHERE user_id=? AND tipo=?", (user_id, tipo)).fetchone()
    if row:
        execute("UPDATE ranking SET cantidad=cantidad+1 WHERE user_id=? AND tipo=?", (user_id, tipo))
    else:
        execute("INSERT INTO ranking VALUES (?,?,?,1)", (user_id, username, tipo))

# ---------------- TIMER ----------------

async def iniciar_timer_raw(user, tipo, horas):
    """Crea un timer. Siempre postea en CANAL_REGISTRO."""
    row    = query("SELECT MAX(numero) FROM timers WHERE user_id=? AND tipo=?", (user.id, tipo)).fetchone()
    numero = 1 if row[0] is None else row[0] + 1

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

    execute(
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

# ---------------- RESET (arreglado para Turso) ----------------

@bot.command()
@commands.has_permissions(administrator=True)
async def resettimers(ctx):
    global dashboard_msg
    execute("DELETE FROM timers")
    execute("DELETE FROM dashboard")
    dashboard_msg = None
    embed = discord.Embed(
        title="🧹 Base de datos reiniciada",
        description="Todos los timers fueron eliminados de Turso.",
        color=0xe74c3c
    )
    add_footer(embed)
    await ctx.send(embed=embed)

# ---------------- AYUDA ----------------

@bot.command()
async def ayuda(ctx):
    embed = discord.Embed(
        title="📖 Comandos — KittyTimer",
        description="Todo lo que podés hacer con el bot.",
        color=0x5865F2
    )
    embed.add_field(
        name="🎮 Panel",
        value="`!panel` — Abre el panel con botones para iniciar timers",
        inline=False
    )
    embed.add_field(
        name="⏱ Timers disponibles",
        value=(
            "`!cajas` — 📦 Cajas · 3h\n"
            "`!robo` — 💰 Robo · 2h\n"
            "`!capataz` — 👷 Capataz · 6h\n"
            "`!cargas` — 🔫 Cargas · 72h\n"
            "`!plantas` — 🌿 Plantas · 3h\n"
            "`!planos6` — 🟣 Planos x6 · 6h\n"
            "`!planos8` — ⬜ Planos x8 · 8h\n"
            "`!planos10` — 🟡 Planos x10 · 10h"
        ),
        inline=False
    )
    embed.add_field(
        name="📋 Gestión",
        value=(
            "`!mistimers` — Ver tus timers activos (con botón para cancelar)\n"
            "`!stats` — Ver tus estadísticas personales\n"
            "`!farmeritos` — Ranking general del server"
        ),
        inline=False
    )
    embed.add_field(
        name="🔧 Admin",
        value="`!resettimers` — Eliminar todos los timers (solo admins)",
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
            await interaction.response.send_message(
                "No podés cancelar timers de otro usuario.",
                ephemeral=True
            )
            return
        execute(
            "DELETE FROM timers WHERE user_id=? AND tipo=? AND numero=?",
            (self.user_id, self.tipo, self.numero)
        )
        embed = discord.Embed(description="🛑 Timer cancelado.", color=0xe74c3c)
        add_footer(embed)
        await interaction.response.edit_message(embed=embed, view=None)

@bot.command()
async def mistimers(ctx):
    timers = query(
        "SELECT * FROM timers WHERE user_id=?",
        (ctx.author.id,)
    ).fetchall()

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

    @discord.ui.button(label="🔫 Cargas",     style=discord.ButtonStyle.secondary, row=0)
    async def cargas(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer(ephemeral=True)
        await iniciar_timer_raw(interaction.user, "Cargas", 72)

    @discord.ui.button(label="🌿 Plantas",    style=discord.ButtonStyle.success,   row=1)
    async def plantas(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer(ephemeral=True)
        await iniciar_timer_raw(interaction.user, "Plantas", 3)

    @discord.ui.button(label="🟣 Planos x6",  style=discord.ButtonStyle.primary,   row=1)
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
    timers = query("SELECT * FROM timers").fetchall()
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
            embed.add_field(
                name="📊 Progreso",
                value="▰" * 14 + " **100%**\n✅ `Finalizado`",
                inline=False
            )
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
    row = query("SELECT msg_id FROM dashboard").fetchone()
    if row:
        try:
            dashboard_msg = await canal.fetch_message(row[0])
        except:
            execute("DELETE FROM dashboard")
            dashboard_msg = None

def build_dashboard_embed():
    timers = query("SELECT * FROM timers").fetchall()
    timers = sorted(timers, key=lambda x: x[5])

    texto = ""
    for t in timers:
        restante = t[5] - now()
        if restante <= 0:
            continue
        icono  = ICONOS.get(t[2], "⏱")
        texto += f"**{icono} {t[2]} #{t[3]}** — <@{t[0]}>\n"
        texto += f"{barra(t[4], t[5])}\n"
        texto += f"🕐 `{hora_arg(t[5])}` · 🌐 `{hora_hub(t[5])}` · <t:{t[5]}:R>\n"
        texto += "─────────────────────\n"

    if not texto:
        texto = "✅ No hay timers activos en este momento."

    embed = discord.Embed(
        title="📊 Dashboard — KittyTimer",
        description=texto,
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
        execute("DELETE FROM dashboard")
        execute("INSERT INTO dashboard VALUES (?)", (dashboard_msg.id,))
    else:
        try:
            await dashboard_msg.edit(embed=embed)
        except discord.NotFound:
            execute("DELETE FROM dashboard")
            dashboard_msg = None
        except Exception:
            pass

# ---------------- FINALIZAR ----------------

@tasks.loop(seconds=10)
async def finalizar():
    lista = query("SELECT * FROM timers WHERE fin <= ?", (now(),)).fetchall()
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

        # Primero avisar, DESPUÉS borrar
        await canal.send(embed=embed)
        execute("DELETE FROM timers WHERE mensaje=?", (t[6],))

# ---------------- STATS ----------------

@bot.command()
async def stats(ctx):
    datos = query(
        "SELECT tipo,cantidad FROM ranking WHERE user_id=?",
        (ctx.author.id,)
    ).fetchall()

    embed = discord.Embed(
        title=f"📊 Estadísticas de {ctx.author.display_name}",
        color=0x3498db
    )
    embed.set_thumbnail(url=ctx.author.display_avatar.url)

    if not datos:
        embed.description = "Todavía no iniciaste ningún timer."
    else:
        total = sum(c for _, c in datos)
        for tipo, cant in sorted(datos, key=lambda x: x[1], reverse=True):
            icono = ICONOS.get(tipo, "⏱")
            embed.add_field(name=f"{icono} {tipo}", value=f"`{cant}` veces", inline=True)
        embed.set_footer(text=f"{BOT_NAME} • Total: {total} timers iniciados")

    add_footer(embed)
    await ctx.send(embed=embed)

# ---------------- RANKING ----------------

@bot.command()
async def farmeritos(ctx):
    embed  = discord.Embed(title="🏆 Farmeritos Vividos", description="Top 5 por categoría", color=0xf1c40f)
    medals = ["🥇", "🥈", "🥉", "4️⃣", "5️⃣"]

    for tipo in ["Cajas", "Robo", "Capataz", "Cargas", "Plantas", "Planos x6", "Planos x8", "Planos x10"]:
        top   = query(
            "SELECT username,cantidad FROM ranking WHERE tipo=? ORDER BY cantidad DESC LIMIT 5",
            (tipo,)
        ).fetchall()
        icono = ICONOS.get(tipo, "⏱")
        texto = "".join(f"{medals[i]} **{u}** — `{c}`\n" for i, (u, c) in enumerate(top)) or "*Sin datos aún*"
        embed.add_field(name=f"{icono} {tipo}", value=texto, inline=True)

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

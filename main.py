import discord
from discord.ext import commands, tasks
import sqlite3
import time
import os
from datetime import datetime, timedelta
import threading
from flask import Flask

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

# ---------------- TOKEN ----------------

TOKEN = os.environ["DISCORD_TOKEN"]

# ---------------- CANALES ----------------

CANAL_REGISTRO  = 1482912693680869426
CANAL_AVISOS    = 1482912285230895205
CANAL_DASHBOARD = 1482912464483127336

# ---------------- DISCORD ----------------

intents = discord.Intents.default()
intents.message_content = True

bot = commands.Bot(command_prefix="!", intents=intents)

# ---------------- DATABASE ----------------

db = sqlite3.connect("timers.db", check_same_thread=False)
cursor = db.cursor()

cursor.execute("""
CREATE TABLE IF NOT EXISTS timers(
user_id INTEGER,
username TEXT,
tipo TEXT,
numero INTEGER,
inicio INTEGER,
fin INTEGER,
mensaje INTEGER
)
""")

cursor.execute("""
CREATE TABLE IF NOT EXISTS ranking(
user_id INTEGER,
username TEXT,
tipo TEXT,
cantidad INTEGER
)
""")

cursor.execute("""
CREATE TABLE IF NOT EXISTS dashboard(
msg_id INTEGER
)
""")

db.commit()

# ---------------- TIEMPO ----------------

def now():
    return int(time.time())

def hora_arg(ts):
    utc = datetime.utcfromtimestamp(ts)
    argentina = utc - timedelta(hours=3)
    return argentina.strftime("%H:%M")

def hora_hub(ts):
    utc = datetime.utcfromtimestamp(ts)
    argentina = utc - timedelta(hours=3)
    hub = argentina + timedelta(hours=3)
    return hub.strftime("%H:%M")

def tiempo_restante(seg):
    horas = seg // 3600
    minutos = (seg % 3600) // 60
    if horas > 0:
        return f"{horas}h {minutos}m"
    else:
        return f"{minutos}m"

# ---------------- BARRA ----------------

def barra(inicio, fin):
    total = fin - inicio
    progreso = now() - inicio

    if progreso < 0:
        progreso = 0
    if progreso > total:
        progreso = total
    if total <= 0:
        porcentaje = 1
    else:
        porcentaje = progreso / total

    bloques = 14
    llenos = int(bloques * porcentaje)
    vacios = bloques - llenos
    bar = "▰" * llenos + "▱" * vacios

    restante = fin - now()
    if restante < 0:
        restante = 0

    return f"{bar} {int(porcentaje*100)}%\n⚡ Restante: {tiempo_restante(restante)}"

# ---------------- RANKING ----------------

def sumar_ranking(user_id, username, tipo):
    cursor.execute(
        "SELECT cantidad FROM ranking WHERE user_id=? AND tipo=?",
        (user_id, tipo)
    )
    data = cursor.fetchone()

    if data:
        cursor.execute(
            "UPDATE ranking SET cantidad=cantidad+1 WHERE user_id=? AND tipo=?",
            (user_id, tipo)
        )
    else:
        cursor.execute(
            "INSERT INTO ranking VALUES (?,?,?,1)",
            (user_id, username, tipo)
        )

    db.commit()

# ---------------- TIMER ----------------

async def iniciar_timer(ctx, tipo, horas):
    cursor.execute(
        "SELECT MAX(numero) FROM timers WHERE user_id=? AND tipo=?",
        (ctx.author.id, tipo)
    )
    data = cursor.fetchone()[0]

    if data is None:
        numero = 1
    else:
        numero = data + 1

    inicio = now()
    fin = inicio + round(horas * 3600)

    embed = discord.Embed(
        title=f"⏱ {tipo} #{numero}",
        color=0x00ffaa
    )
    embed.add_field(name="Usuario", value=ctx.author.mention, inline=False)
    embed.add_field(name="Progreso", value=barra(inicio, fin), inline=False)
    embed.add_field(name="Fin ARG", value=hora_arg(fin))
    embed.add_field(name="Fin HUB", value=hora_hub(fin))

    msg = await ctx.send(embed=embed)

    cursor.execute(
        "INSERT INTO timers VALUES (?,?,?,?,?,?,?)",
        (ctx.author.id, ctx.author.name, tipo, numero, inicio, fin, msg.id)
    )
    db.commit()

    sumar_ranking(ctx.author.id, ctx.author.name, tipo)

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
@commands.has_permissions(administrator=True)
async def resettimers(ctx):
    global db
    try:
        db.close()
    except:
        pass
    if os.path.exists("timers.db"):
        os.remove("timers.db")
    await ctx.send("🧹 Base de datos de timers reiniciada. Reiniciando bot...")
    os._exit(0)

# ---------------- CANCELAR TIMER ----------------

@bot.command()
async def cancelar(ctx, tipo, numero: int):
    cursor.execute(
        "DELETE FROM timers WHERE user_id=? AND tipo=? AND numero=?",
        (ctx.author.id, tipo.capitalize(), numero)
    )
    db.commit()
    await ctx.send(f"🛑 {tipo} #{numero} cancelado.")

# ---------------- VER MIS TIMERS ----------------

class CancelarView(discord.ui.View):

    def __init__(self, user_id, tipo, numero):
        super().__init__(timeout=None)
        self.user_id = user_id
        self.tipo = tipo
        self.numero = numero

    @discord.ui.button(label="❌ Cancelar", style=discord.ButtonStyle.danger)
    async def cancelar(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message(
                "No puedes cancelar timers de otro usuario.",
                ephemeral=True
            )
            return

        cursor.execute(
            "DELETE FROM timers WHERE user_id=? AND tipo=? AND numero=?",
            (self.user_id, self.tipo, self.numero)
        )
        db.commit()

        await interaction.response.edit_message(
            content="🛑 Timer cancelado",
            embed=None,
            view=None
        )

@bot.command()
async def mistimers(ctx):
    cursor.execute("SELECT * FROM timers WHERE user_id=?", (ctx.author.id,))
    timers = cursor.fetchall()

    if not timers:
        await ctx.send("No tienes timers activos.")
        return

    for t in timers:
        embed = discord.Embed(title=f"{t[2]} #{t[3]}", color=0x3498db)
        embed.add_field(name="Progreso", value=barra(t[4], t[5]), inline=False)
        await ctx.send(embed=embed, view=CancelarView(ctx.author.id, t[2], t[3]))

# ---------------- PANEL ----------------

class Panel(discord.ui.View):

    # --- Fila 1 ---

    @discord.ui.button(label="📦 Cajas", style=discord.ButtonStyle.primary, row=0)
    async def cajas(self, interaction: discord.Interaction, button: discord.ui.Button):
        ctx = await bot.get_context(interaction.message)
        ctx.author = interaction.user
        await iniciar_timer(ctx, "Cajas", 3)
        await interaction.response.defer()

    @discord.ui.button(label="💰 Robo", style=discord.ButtonStyle.danger, row=0)
    async def robo(self, interaction: discord.Interaction, button: discord.ui.Button):
        ctx = await bot.get_context(interaction.message)
        ctx.author = interaction.user
        await iniciar_timer(ctx, "Robo", 2)
        await interaction.response.defer()

    @discord.ui.button(label="👷 Capataz", style=discord.ButtonStyle.success, row=0)
    async def capataz(self, interaction: discord.Interaction, button: discord.ui.Button):
        ctx = await bot.get_context(interaction.message)
        ctx.author = interaction.user
        await iniciar_timer(ctx, "Capataz", 6)
        await interaction.response.defer()

    @discord.ui.button(label="🔫 Cargas", style=discord.ButtonStyle.secondary, row=0)
    async def cargas(self, interaction: discord.Interaction, button: discord.ui.Button):
        ctx = await bot.get_context(interaction.message)
        ctx.author = interaction.user
        await iniciar_timer(ctx, "Cargas", 72)
        await interaction.response.defer()

    # --- Fila 2 ---

    @discord.ui.button(label="🌿 Plantas", style=discord.ButtonStyle.success, row=1)
    async def plantas(self, interaction: discord.Interaction, button: discord.ui.Button):
        ctx = await bot.get_context(interaction.message)
        ctx.author = interaction.user
        await iniciar_timer(ctx, "Plantas", 3)
        await interaction.response.defer()

    @discord.ui.button(label="🟣 Planos x6", style=discord.ButtonStyle.primary, row=1)
    async def planos6(self, interaction: discord.Interaction, button: discord.ui.Button):
        ctx = await bot.get_context(interaction.message)
        ctx.author = interaction.user
        await iniciar_timer(ctx, "Planos x6", 6)
        await interaction.response.defer()

    @discord.ui.button(label="⬜ Planos x8", style=discord.ButtonStyle.secondary, row=1)
    async def planos8(self, interaction: discord.Interaction, button: discord.ui.Button):
        ctx = await bot.get_context(interaction.message)
        ctx.author = interaction.user
        await iniciar_timer(ctx, "Planos x8", 8)
        await interaction.response.defer()

    @discord.ui.button(label="🟡 Planos x10", style=discord.ButtonStyle.secondary, row=1)
    async def planos10(self, interaction: discord.Interaction, button: discord.ui.Button):
        ctx = await bot.get_context(interaction.message)
        ctx.author = interaction.user
        await iniciar_timer(ctx, "Planos x10", 10)
        await interaction.response.defer()

@bot.command()
async def panel(ctx):
    embed = discord.Embed(
        title="🎮 Panel de Timers",
        description=(
            "**Fila 1 — Farm principal**\n"
            "📦 Cajas · 3h  |  💰 Robo · 2h  |  👷 Capataz · 6h  |  🔫 Cargas · 72h\n\n"
            "**Fila 2 — Plantas & Planos**\n"
            "🌿 Plantas · 3h  |  🟣 Planos x6 · 6h  |  ⬜ Planos x8 · 8h  |  🟡 Planos x10 · 10h"
        ),
        color=0x5865F2
    )
    await ctx.send(embed=embed, view=Panel())

# ---------------- ACTUALIZAR BARRAS ----------------

@tasks.loop(seconds=10)
async def actualizar_barras():
    cursor.execute("SELECT * FROM timers")
    timers = cursor.fetchall()

    canal = bot.get_channel(CANAL_REGISTRO)
    if canal is None:
        return

    for t in timers:
        inicio = t[4]
        fin = t[5]

        embed = discord.Embed(title=f"⏱ {t[2]} #{t[3]}", color=0x00ffaa)
        embed.add_field(name="Usuario", value=f"<@{t[0]}>", inline=False)

        if now() >= fin:
            embed.add_field(
                name="Progreso",
                value="▰" * 14 + " 100%\n✅ Finalizado",
                inline=False
            )
        else:
            embed.add_field(name="Progreso", value=barra(inicio, fin), inline=False)

        embed.add_field(name="Fin ARG", value=hora_arg(fin))
        embed.add_field(name="Fin HUB", value=hora_hub(fin))

        try:
            msg = await canal.fetch_message(t[6])
            await msg.edit(embed=embed)
        except:
            pass

# ---------------- DASHBOARD ----------------

dashboard_msg = None

@tasks.loop(seconds=10)
async def dashboard():
    global dashboard_msg

    canal = bot.get_channel(CANAL_DASHBOARD)
    if canal is None:
        return

    cursor.execute("SELECT msg_id FROM dashboard")
    data = cursor.fetchone()

    if data:
        try:
            dashboard_msg = await canal.fetch_message(data[0])
        except:
            dashboard_msg = None

    cursor.execute("SELECT * FROM timers")
    timers = cursor.fetchall()
    timers = sorted(timers, key=lambda x: x[5])

    texto = ""

    for t in timers:
        restante = t[5] - now()
        if restante <= 0:
            continue
        texto += f"👤 <@{t[0]}>\n"
        texto += f"🎯 {t[2]} #{t[3]}\n"
        texto += f"{barra(t[4], t[5])}\n"
        texto += f"Fin ARG: {hora_arg(t[5])}\n"
        texto += f"Fin HUB: {hora_hub(t[5])}\n\n"

    if texto == "":
        texto = "No hay timers activos."

    embed = discord.Embed(
        title="📊 Dashboard Farm Server",
        description=texto,
        color=0x2ecc71
    )

    if dashboard_msg is None:
        dashboard_msg = await canal.send(embed=embed)
        cursor.execute("DELETE FROM dashboard")
        cursor.execute("INSERT INTO dashboard VALUES (?)", (dashboard_msg.id,))
        db.commit()
    else:
        try:
            await dashboard_msg.edit(embed=embed)
        except:
            dashboard_msg = None

# ---------------- FINALIZAR ----------------

@tasks.loop(seconds=10)
async def finalizar():
    cursor.execute("SELECT * FROM timers WHERE fin <= ?", (now(),))
    lista = cursor.fetchall()

    canal = bot.get_channel(CANAL_AVISOS)
    if canal is None:
        return

    for t in lista:
        user = await bot.fetch_user(t[0])

        embed = discord.Embed(
            title="✅ Timer terminado",
            description=f"{user.mention} terminó **{t[2]} #{t[3]}**",
            color=0x00ff00
        )
        await canal.send(embed=embed)

        cursor.execute("DELETE FROM timers WHERE mensaje=?", (t[6],))
        db.commit()

# ---------------- STATS ----------------

@bot.command()
async def stats(ctx):
    cursor.execute(
        "SELECT tipo,cantidad FROM ranking WHERE user_id=?",
        (ctx.author.id,)
    )
    datos = cursor.fetchall()

    embed = discord.Embed(
        title=f"📊 Estadísticas de {ctx.author.name}",
        color=0x3498db
    )
    for tipo, cant in datos:
        embed.add_field(name=tipo, value=f"{cant}", inline=False)

    await ctx.send(embed=embed)

# ---------------- RANKING ----------------

@bot.command()
async def farmeritos(ctx):
    embed = discord.Embed(title="🏆 Farmeritos Vividos", color=0xf1c40f)

    for tipo in ["Cajas", "Robo", "Capataz", "Cargas", "Plantas", "Planos x6", "Planos x8", "Planos x10"]:
        cursor.execute(
            "SELECT username,cantidad FROM ranking WHERE tipo=? ORDER BY cantidad DESC LIMIT 5",
            (tipo,)
        )
        top = cursor.fetchall()

        medals = ["🥇", "🥈", "🥉", "4️⃣", "5️⃣"]
        texto = ""

        for i, (user, cant) in enumerate(top):
            texto += f"{medals[i]} {user} — {cant}\n"

        if texto == "":
            texto = "Sin datos"

        embed.add_field(name=tipo, value=texto, inline=False)

    await ctx.send(embed=embed)

# ---------------- READY ----------------

@bot.event
async def on_ready():
    print("Bot conectado como", bot.user)
    dashboard.start()
    finalizar.start()
    actualizar_barras.start()

bot.run(TOKEN)

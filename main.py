import discord
from discord.ext import commands
import yt_dlp
import asyncio
import random
import os

intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!!", intents=intents)

# ================= 설정 =================
ytdl_format_options = {
    'format': 'bestaudio/best',
    'quiet': True,
    'noplaylist': True,
    'force_ipv4': True,
    'extractor_args': {
        'youtube': {
            'player_client': ['android', 'web']
        }
    }
}

ffmpeg_options = {
    'before_options': '-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5',
    'options': '-vn'
}

ytdl = yt_dlp.YoutubeDL(ytdl_format_options)

queue = {}
now_playing = {}
now_playing_info = {}
player_message = {}
player_state = {}

# ================= 유틸 =================
def format_time(seconds):
    if not seconds:
        return "00:00"
    m, s = divmod(int(seconds), 60)
    return f"{m:02d}:{s:02d}"

def make_progress_bar(current, total, length=20):
    if total == 0:
        return "─" * length
    filled = int(length * current / total)
    return "█" * filled + "─" * (length - filled)

# ================= YTDL =================
class YTDLSource(discord.PCMVolumeTransformer):
    def __init__(self, source, *, data):
        super().__init__(source, volume=0.5)
        self.title = data.get('title')
        self.url = data.get('webpage_url')
        self.thumbnail = data.get('thumbnail')
        self.duration = data.get('duration', 0)

    @classmethod
    async def from_url(cls, url, *, loop):
        data = await loop.run_in_executor(None, lambda: ytdl.extract_info(url, download=False))
        if 'entries' in data:
            data = data['entries'][0]

        return cls(
            discord.FFmpegPCMAudio(data['url'], executable="ffmpeg", **ffmpeg_options),
            data=data
        )

# ================= UI =================
async def update_player(ctx, player):
    gid = ctx.guild.id

    start_time, duration = now_playing_info.get(gid, (0, 0))
    current = max(0, int(asyncio.get_event_loop().time() - start_time))

    bar = make_progress_bar(current, duration)

    embed = discord.Embed(
        title="🎧 MUSIC PLAYER",
        description=f"**{player.title}**\n\n`{format_time(current)} [{bar}] {format_time(duration)}`",
        color=discord.Color.purple()
    )
    embed.set_thumbnail(url=player.thumbnail)

    if gid in player_message:
        try:
            await player_message[gid].edit(embed=embed, view=PlayerView(ctx))
            return
        except:
            pass

    msg = await ctx.send(embed=embed, view=PlayerView(ctx))
    player_message[gid] = msg

# ================= 자동 업데이트 =================
async def player_updater(ctx, player):
    gid = ctx.guild.id

    while True:
        vc = ctx.voice_client

        if not vc or not vc.is_playing():
            break

        await update_player(ctx, player)
        await asyncio.sleep(5)

# ================= 플레이어 =================
class PlayerView(discord.ui.View):
    def __init__(self, ctx):
        super().__init__(timeout=None)
        self.ctx = ctx

    async def safe_defer(self, interaction):
        try:
            if not interaction.response.is_done():
                await interaction.response.defer()
        except:
            pass

    @discord.ui.button(label="⏯", style=discord.ButtonStyle.primary)
    async def play_pause(self, interaction, button):
        await self.safe_defer(interaction)
        vc = self.ctx.voice_client

        if vc.is_playing():
            vc.pause()
        else:
            vc.resume()

    @discord.ui.button(label="⏭", style=discord.ButtonStyle.secondary)
    async def skip(self, interaction, button):
        await self.safe_defer(interaction)
        if self.ctx.voice_client:
            self.ctx.voice_client.stop()

    @discord.ui.button(label="📜", style=discord.ButtonStyle.success)
    async def queue_btn(self, interaction, button):
        q = queue.get(self.ctx.guild.id, [])
        msg = "\n".join([f"{i+1}. {x}" for i, x in enumerate(q[:10])]) or "비어있음"
        await interaction.response.send_message(f"📜 큐:\n{msg}", ephemeral=True)

    @discord.ui.button(label="⏹", style=discord.ButtonStyle.danger)
    async def stop(self, interaction, button):
        await self.safe_defer(interaction)
        if self.ctx.voice_client:
            await self.ctx.voice_client.disconnect()
            queue[self.ctx.guild.id] = []

# ================= 재생 =================
async def play_next(ctx):
    if not ctx.voice_client:
        return

    gid = ctx.guild.id

    if not queue.get(gid):
        return

    url = queue[gid].pop(0)

    try:
        player = await YTDLSource.from_url(url, loop=bot.loop)
    except:
        await play_next(ctx)
        return

    now_playing[gid] = url
    now_playing_info[gid] = (asyncio.get_event_loop().time(), player.duration)

    ctx.voice_client.play(
        player,
        after=lambda e: asyncio.run_coroutine_threadsafe(play_next(ctx), bot.loop)
    )

    await update_player(ctx, player)
    bot.loop.create_task(player_updater(ctx, player))

# ================= 검색 =================
async def search_youtube(query):
    data = await bot.loop.run_in_executor(
        None,
        lambda: ytdl.extract_info(f"ytsearch5:{query}", download=False)
    )
    return data['entries']

class SearchView(discord.ui.View):
    def __init__(self, ctx, results):
        super().__init__(timeout=30)
        self.ctx = ctx

        for i, r in enumerate(results):
            self.add_item(SearchButton(i, r))

class SearchButton(discord.ui.Button):
    def __init__(self, index, data):
        super().__init__(label=str(index+1), style=discord.ButtonStyle.primary)
        self.data = data

    async def callback(self, interaction: discord.Interaction):
        ctx = self.view.ctx
        gid = ctx.guild.id

        try:
            await interaction.response.defer()

            url = self.data['webpage_url']
            queue.setdefault(gid, [])

            vc = ctx.voice_client
            if not vc or not vc.is_connected():
                vc = await ctx.author.voice.channel.connect()
                await asyncio.sleep(1)

            embed = discord.Embed(
                title="🎵 선택됨",
                description=self.data['title'],
                color=discord.Color.green()
            )
            embed.set_thumbnail(url=self.data['thumbnail'])

            queue[gid].append(url)

            if not vc.is_playing():
                await play_next(ctx)

            await interaction.followup.send(embed=embed)

            self.view.stop()

        except Exception as e:
            try:
                await interaction.followup.send(f"❌ 에러: {e}")
            except:
                pass

# ================= 명령어 =================
@bot.command()
async def 검색(ctx, *, query):
    if not ctx.author.voice:
        await ctx.send("음성 채널 먼저 들어가셈")
        return

    results = await search_youtube(query)

    desc = "\n".join([f"{i+1}. {r['title']}" for i, r in enumerate(results)])

    embed = discord.Embed(title="🔍 검색 결과", description=desc)
    embed.set_thumbnail(url=results[0]['thumbnail'])

    await ctx.send(embed=embed, view=SearchView(ctx, results))

# ================= 실행 =================
import os

bot.run(os.getenv("DISCORD_TOKEN"))

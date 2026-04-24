import discord
from discord.ext import commands, tasks
import yt_dlp
import asyncio
import os

intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!!", intents=intents)

# 🔥 yt-dlp 설정 (차단 대응)
ytdl_opts = {
    'format': 'bestaudio/best',
    'quiet': True,
    'noplaylist': True,
    'extractor_args': {
        'youtube': {
            'player_client': ['android', 'web']
        }
    },
    'http_headers': {
        'User-Agent': 'Mozilla/5.0'
    }
}

ffmpeg_opts = {
    'before_options': '-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5',
    'options': '-vn'
}

ytdl = yt_dlp.YoutubeDL(ytdl_opts)

queue = []
current = None
start_time = 0


# 🔊 음성 연결 안정 함수 (핵심)
async def ensure_voice(ctx):
    if not ctx.author.voice:
        await ctx.send("❌ 음성 채널에 먼저 들어가세요")
        return None

    channel = ctx.author.voice.channel
    vc = ctx.voice_client

    if vc is None:
        vc = await channel.connect()
    elif vc.channel != channel:
        await vc.move_to(channel)

    return vc


# 🎵 소스 생성
async def create_source(url):
    loop = asyncio.get_event_loop()
    try:
        data = await loop.run_in_executor(None, lambda: ytdl.extract_info(url, download=False))
    except:
        return None

    if 'entries' in data:
        data = data['entries'][0]

    try:
        return {
            'audio': discord.FFmpegPCMAudio(data['url'], **ffmpeg_opts),
            'title': data.get('title'),
            'thumbnail': data.get('thumbnail'),
            'duration': data.get('duration', 0),
            'url': data.get('webpage_url')
        }
    except:
        return None


# 📊 프로그레스바
def progress_bar(elapsed, total, length=20):
    if total == 0:
        return "🔴 LIVE"
    filled = int(length * elapsed / total)
    return "█" * filled + "─" * (length - filled)


# 🔁 다음곡
async def play_next(ctx):
    global current, start_time

    vc = ctx.voice_client
    if not vc:
        return

    while queue:
        url = queue.pop(0)
        source = await create_source(url)

        if source is None:
            await ctx.send("⚠️ 재생 실패 → 다음 곡")
            continue

        current = source
        start_time = asyncio.get_event_loop().time()

        def after_playing(e):
            asyncio.run_coroutine_threadsafe(play_next(ctx), bot.loop)

        vc.play(source['audio'], after=after_playing)
        await send_now_playing(ctx)
        return

    await ctx.send("📭 큐 종료")


# 🎵 현재곡 UI
async def send_now_playing(ctx):
    embed = discord.Embed(
        title="🎵 재생 중",
        description=current['title']
    )
    embed.set_thumbnail(url=current['thumbnail'])

    view = PlayerView(ctx)
    msg = await ctx.send(embed=embed, view=view)

    update_progress.start(msg)


# 🔄 프로그레스 업데이트
@tasks.loop(seconds=5)
async def update_progress(message):
    global current, start_time

    if not current:
        return

    elapsed = int(asyncio.get_event_loop().time() - start_time)
    total = current['duration']

    bar = progress_bar(elapsed, total)

    embed = discord.Embed(
        title="🎵 재생 중",
        description=f"{current['title']}\n\n{bar} {elapsed}s / {total}s"
    )
    embed.set_thumbnail(url=current['thumbnail'])

    try:
        await message.edit(embed=embed)
    except:
        update_progress.stop()


# 🔍 검색
@bot.command(name="검색")
async def search(ctx, *, query):
    await ctx.send("🔍 검색 중...")

    try:
        data = await asyncio.get_event_loop().run_in_executor(
            None, lambda: ytdl.extract_info(f"ytsearch5:{query}", download=False)
        )
    except:
        await ctx.send("❌ 검색 제한됨 → !!재생 URL 사용")
        return

    results = data.get('entries', [])

    embed = discord.Embed(title="🔎 검색 결과")

    for i, entry in enumerate(results):
        embed.add_field(name=f"{i+1}.", value=entry['title'], inline=False)

    await ctx.send(embed=embed, view=SearchView(results, ctx))


# 🔘 검색 버튼
class SearchView(discord.ui.View):
    def __init__(self, results, ctx):
        super().__init__(timeout=30)
        self.results = results
        self.ctx = ctx

        for i in range(len(results)):
            self.add_item(SearchButton(i, results, ctx))


class SearchButton(discord.ui.Button):
    def __init__(self, index, results, ctx):
        super().__init__(label=str(index+1))
        self.index = index
        self.results = results
        self.ctx = ctx

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.defer()

        vc = await ensure_voice(self.ctx)
        if not vc:
            return

        url = self.results[self.index]['webpage_url']
        queue.append(url)

        await interaction.followup.send(f"✅ 추가됨: {self.results[self.index]['title']}")

        if not vc.is_playing():
            await play_next(self.ctx)


# 🎮 플레이어 UI
class PlayerView(discord.ui.View):
    def __init__(self, ctx):
        super().__init__(timeout=None)
        self.ctx = ctx

    @discord.ui.button(label="⏯")
    async def pause(self, interaction, button):
        vc = self.ctx.voice_client
        if vc.is_playing():
            vc.pause()
        else:
            vc.resume()
        await interaction.response.defer()

    @discord.ui.button(label="⏭")
    async def skip(self, interaction, button):
        self.ctx.voice_client.stop()
        await interaction.response.defer()

    @discord.ui.button(label="⏹")
    async def stop(self, interaction, button):
        await self.ctx.voice_client.disconnect()
        await interaction.response.defer()


# ▶ 재생
@bot.command(name="재생")
async def play(ctx, url: str):
    vc = await ensure_voice(ctx)
    if not vc:
        return

    queue.append(url)
    await ctx.send("✅ 큐 추가됨")

    if not vc.is_playing():
        await play_next(ctx)


# 📜 큐
@bot.command(name="큐")
async def show_queue(ctx):
    if not queue:
        await ctx.send("📭 큐 비어있음")
        return

    text = "\n".join([f"{i+1}. {q}" for i, q in enumerate(queue)])
    await ctx.send(f"📜 큐 목록:\n{text}")


@bot.event
async def on_ready():
    print(f"✅ 로그인 완료: {bot.user}")


bot.run(os.getenv("DISCORD_TOKEN"))

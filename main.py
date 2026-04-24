import discord
from discord.ext import commands, tasks
import yt_dlp
import asyncio
import os
import random

intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)

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


# 🎵 소스 생성
async def create_source(url):
    loop = asyncio.get_event_loop()
    try:
        data = await loop.run_in_executor(None, lambda: ytdl.extract_info(url, download=False))
    except:
        return None

    if 'entries' in data:
        data = data['entries'][0]

    return {
        'audio': discord.FFmpegPCMAudio(data['url'], **ffmpeg_opts),
        'title': data.get('title'),
        'url': data.get('webpage_url'),
        'thumbnail': data.get('thumbnail'),
        'duration': data.get('duration', 0)
    }


# 📊 프로그레스바
def progress_bar(elapsed, total, length=20):
    if total == 0:
        return "🔴 LIVE"
    filled = int(length * elapsed / total)
    return "█" * filled + "─" * (length - filled)


# 🔁 자동 다음곡 + 추천
async def play_next(ctx):
    global current, start_time

    if not queue:
        # 🎵 자동 추천
        if current:
            search = current['title']
            try:
                data = ytdl.extract_info(f"ytsearch1:{search}", download=False)
                queue.append(data['entries'][0]['webpage_url'])
                await ctx.send("🔄 자동 추천 곡 추가됨")
            except:
                await ctx.send("📭 재생 종료")
                return

    vc = ctx.voice_client

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


# 🎵 현재곡 UI
async def send_now_playing(ctx):
    global current

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


# 🔍 검색 (Spotify 스타일 느낌)
@bot.command(name="검색")
async def search(ctx, *, query):
    await ctx.send("🔍 검색 중...")

    try:
        data = ytdl.extract_info(f"ytsearch5:{query}", download=False)
    except:
        await ctx.send("❌ 검색 제한됨 → URL 사용")
        return

    results = data.get('entries', [])
    embed = discord.Embed(title="🎧 검색 결과 (Spotify 스타일)")

    for i, entry in enumerate(results):
        embed.add_field(
            name=f"{i+1}. {entry['title']}",
            value="▶ 클릭해서 재생",
            inline=False
        )

    await ctx.send(embed=embed, view=SearchView(results, ctx))


# 🔘 버튼
class SearchView(discord.ui.View):
    def __init__(self, results, ctx):
        super().__init__(timeout=30)
        self.ctx = ctx
        self.results = results

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

        url = self.results[self.index]['webpage_url']
        queue.append(url)

        await interaction.followup.send(f"✅ 추가됨: {self.results[self.index]['title']}")

        vc = self.ctx.voice_client
        if not vc:
            vc = await self.ctx.author.voice.channel.connect()

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
    queue.append(url)
    await ctx.send("✅ 큐 추가됨")

    vc = ctx.voice_client
    if not vc:
        vc = await ctx.author.voice.channel.connect()

    if not vc.is_playing():
        await play_next(ctx)


@bot.event
async def on_ready():
    print(f"✅ 로그인 완료: {bot.user}")


bot.run(os.getenv("DISCORD_TOKEN"))

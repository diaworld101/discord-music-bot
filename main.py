import discord
from discord.ext import commands
import yt_dlp
import asyncio
import os

intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!!", intents=intents)

# 🔥 차단 대응 yt-dlp 설정
ytdl_opts = {
    'format': 'bestaudio/best',
    'quiet': True,
    'noplaylist': True,
    'extractor_args': {
        'youtube': {
            'player_client': ['android', 'web'],
            'skip': ['hls', 'dash']
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


# 🎵 소스 생성 (차단 대응)
async def create_source(url):
    loop = asyncio.get_event_loop()

    try:
        data = await loop.run_in_executor(None, lambda: ytdl.extract_info(url, download=False))
    except Exception:
        return None

    if 'entries' in data:
        data = data['entries'][0]

    try:
        return {
            'audio': discord.FFmpegPCMAudio(data['url'], **ffmpeg_opts),
            'title': data.get('title'),
            'thumbnail': data.get('thumbnail'),
            'url': data.get('webpage_url')
        }
    except:
        return None


# 🔁 다음곡 자동 재생 (핵심 안정 로직)
async def play_next(ctx):
    global current

    if not queue:
        await ctx.send("📭 재생할 곡 없음")
        return

    vc = ctx.voice_client

    while queue:
        url = queue.pop(0)
        source = await create_source(url)

        if source is None:
            await ctx.send("⚠️ 재생 실패 → 다음 곡 시도")
            continue

        current = source

        def after_playing(e):
            asyncio.run_coroutine_threadsafe(play_next(ctx), bot.loop)

        vc.play(source['audio'], after=after_playing)

        embed = discord.Embed(
            title="🎵 재생 중",
            description=source['title']
        )
        embed.set_thumbnail(url=source['thumbnail'])

        await ctx.send(embed=embed)
        return


# 🔍 검색 (차단 대응)
@bot.command(name="검색")
async def search(ctx, *, query):
    await ctx.send("🔍 검색 중...")

    loop = asyncio.get_event_loop()

    try:
        data = await loop.run_in_executor(
            None,
            lambda: ytdl.extract_info(f"ytsearch5:{query}", download=False)
        )
    except Exception:
        await ctx.send("❌ 유튜브 차단됨\n👉 !재생 <URL> 사용해주세요")
        return

    results = data.get('entries', [])
    if not results:
        await ctx.send("❌ 결과 없음")
        return

    embed = discord.Embed(title="🔎 검색 결과")

    for i, entry in enumerate(results):
        embed.add_field(name=f"{i+1}.", value=entry['title'], inline=False)

    await ctx.send(embed=embed, view=SearchView(results, ctx))


# 🔘 버튼 UI
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

        await interaction.followup.send(f"✅ 큐 추가됨: {self.results[self.index]['title']}")

        vc = self.ctx.voice_client
        if not vc or not vc.is_connected():
            if self.ctx.author.voice:
                await self.ctx.author.voice.channel.connect()
            else:
                await interaction.followup.send("❌ 음성채널 없음")
                return

        if not vc.is_playing():
            await play_next(self.ctx)


# ▶ URL 재생 (핵심 안정 기능)
@bot.command(name="재생")
async def play(ctx, url: str):
    queue.append(url)
    await ctx.send("✅ 큐 추가됨")

    vc = ctx.voice_client

    if not vc:
        if ctx.author.voice:
            vc = await ctx.author.voice.channel.connect()
        else:
            await ctx.send("❌ 음성채널 없음")
            return

    if not vc.is_playing():
        await play_next(ctx)


# ⏭ 스킵
@bot.command(name="스킵")
async def skip(ctx):
    if ctx.voice_client:
        ctx.voice_client.stop()
        await ctx.send("⏭ 스킵")


# ⏹ 정지
@bot.command(name="정지")
async def stop(ctx):
    if ctx.voice_client:
        await ctx.voice_client.disconnect()
        await ctx.send("⏹ 정지")


# 📜 큐 확인
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

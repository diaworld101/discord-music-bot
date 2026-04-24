import discord
from discord.ext import commands
import yt_dlp
import asyncio
import os

intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!!", intents=intents)

# 🔥 yt-dlp 안정 설정 (차단 회피 포함)
ytdl_format_options = {
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

ffmpeg_options = {
    'before_options': '-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5',
    'options': '-vn'
}

ytdl = yt_dlp.YoutubeDL(ytdl_format_options)

queue = []
current = None


class YTDLSource(discord.PCMVolumeTransformer):
    def __init__(self, source, *, data):
        super().__init__(source)
        self.title = data.get('title')
        self.url = data.get('webpage_url')
        self.thumbnail = data.get('thumbnail')


async def create_source(url):
    loop = asyncio.get_event_loop()
    try:
        data = await loop.run_in_executor(None, lambda: ytdl.extract_info(url, download=False))
    except Exception:
        return None

    if 'entries' in data:
        data = data['entries'][0]

    return YTDLSource(
        discord.FFmpegPCMAudio(data['url'], **ffmpeg_options),
        data=data
    )


# 🔥 자동 다음곡
def play_next(ctx):
    global current

    if len(queue) > 0:
        url = queue.pop(0)

        async def play():
            global current
            source = await create_source(url)
            if source is None:
                await ctx.send("❌ 재생 실패 → 다음 곡")
                play_next(ctx)
                return

            current = source
            vc = ctx.voice_client

            vc.play(source, after=lambda e: asyncio.run_coroutine_threadsafe(after_play(ctx), bot.loop))

            embed = discord.Embed(title="🎵 재생 중", description=source.title)
            embed.set_thumbnail(url=source.thumbnail)
            await ctx.send(embed=embed)

        asyncio.run_coroutine_threadsafe(play(), bot.loop)


async def after_play(ctx):
    play_next(ctx)


# 🔍 검색
@bot.command(name="검색")
async def search(ctx, *, query):
    await ctx.send("🔍 검색 중...")

    loop = asyncio.get_event_loop()
    data = await loop.run_in_executor(None, lambda: ytdl.extract_info(f"ytsearch5:{query}", download=False))

    results = data['entries']

    embed = discord.Embed(title="🔎 검색 결과")

    for i, entry in enumerate(results):
        embed.add_field(name=f"{i+1}.", value=entry['title'], inline=False)

    view = SearchView(results, ctx)
    await ctx.send(embed=embed, view=view)


# 🔘 검색 버튼 UI
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

        url = self.results[self.index]['webpage_url']
        queue.append(url)

        await interaction.followup.send(f"✅ 큐 추가됨: {self.results[self.index]['title']}")

        vc = self.ctx.voice_client
        if not vc.is_playing():
            play_next(self.ctx)


# 🎮 컨트롤 UI
class PlayerView(discord.ui.View):
    def __init__(self, ctx):
        super().__init__(timeout=None)
        self.ctx = ctx

    @discord.ui.button(label="⏯")
    async def pause(self, interaction: discord.Interaction, button: discord.ui.Button):
        vc = self.ctx.voice_client
        if vc.is_playing():
            vc.pause()
        else:
            vc.resume()
        await interaction.response.defer()

    @discord.ui.button(label="⏭")
    async def skip(self, interaction: discord.Interaction, button: discord.ui.Button):
        vc = self.ctx.voice_client
        vc.stop()
        await interaction.response.defer()

    @discord.ui.button(label="⏹")
    async def stop(self, interaction: discord.Interaction, button: discord.ui.Button):
        vc = self.ctx.voice_client
        await vc.disconnect()
        await interaction.response.defer()


# 🎵 입장 + 초기 UI
@bot.command(name="입장")
async def join(ctx):
    if ctx.author.voice:
        channel = ctx.author.voice.channel
        await channel.connect()
        await ctx.send("✅ 음성채널 입장 완료", view=PlayerView(ctx))
    else:
        await ctx.send("❌ 음성 채널에 먼저 들어가세요")


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


# 🔐 토큰 (환경 변수)
bot.run(os.getenv("DISCORD_TOKEN"))

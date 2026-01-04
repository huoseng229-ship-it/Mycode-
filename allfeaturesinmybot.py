import os
import asyncio
import discord
import wavelink
import requests
from discord import app_commands
from discord.ext import commands
from dotenv import load_dotenv
from urllib.parse import urlparse, parse_qs
import re 

# ================== ENV CONFIG ==================
load_dotenv()
TOKEN = os.getenv("DISCORD_TOKEN")
if not TOKEN:
    raise ValueError("⚠️ Không tìm thấy DISCORD_TOKEN trong file .env hoặc biến môi trường.")

LAVALINK_URI = os.getenv("LAVALINK_URI", "http://193.226.78.187:8389")
LAVALINK_PASSWORD = os.getenv("LAVALINK_PASSWORD", "Seng")

# ================== BOT SETUP ==================
intents = discord.Intents.default()
intents.message_content = True 
intents.voice_states = True
intents.guilds = True

bot = commands.Bot(command_prefix="!", intents=intents) 
tree = bot.tree

# ================== MUSIC UTILS ==================
def get_youtube_thumbnail(url: str):
    """
    Lấy thumbnail HQ (High Quality) từ link YouTube.
    """
    if not url:
        return None
    
    THUMBNAIL_URL_BASE = "https://img.youtube.com/vi/{video_id}/hqdefault.jpg"
    patterns = [
        r"(?:v=|v\/|embed\/|youtu\.be\/|\/v=)([^&?\"'>]+)",
        r"(?<=v=)[^&]+",
    ]

    video_id = None
    parsed_url = urlparse(url)
    
    query_params = parse_qs(parsed_url.query)
    if 'v' in query_params:
        video_id = query_params['v'][0]
    
    elif 'youtu.be' in parsed_url.netloc:
        path_segments = parsed_url.path.strip('/').split('/')
        if path_segments and path_segments[0]:
            video_id = path_segments[0]
            
    if not video_id:
        for pattern in patterns:
            match = re.search(pattern, url)
            if match:
                video_id = match.group(1)
                break
    
    if video_id:
        return THUMBNAIL_URL_BASE.format(video_id=video_id)
        
    return None

def is_url(query: str):
    """Kiểm tra nếu chuỗi là URL hợp lệ."""
    try:
        result = urlparse(query)
        return all([result.scheme, result.netloc])
    except ValueError:
        return False

# ================== VOICE CLIENT HANDLING ==================

async def get_or_connect_vc(interaction: discord.Interaction, player_type: type):
    """Kết nối bot hoặc chuyển đổi Voice Client sang player_type (wavelink.Player hoặc discord.VoiceClient)."""
    if not interaction.user.voice:
        return None, "❌ Bạn chưa ở voice channel!"

    vc = interaction.guild.voice_client

    if not vc:
        # Connect if not connected
        vc = await interaction.user.voice.channel.connect(cls=player_type)
        if player_type == wavelink.Player:
            asyncio.create_task(auto_disconnect(vc))
        return vc, None
    
    # Check if the existing VC is the required type
    if not isinstance(vc, player_type):
        # Disconnect the old type and connect the new type
        await vc.disconnect()
        vc = await interaction.user.voice.channel.connect(cls=player_type)
        if player_type == wavelink.Player:
            asyncio.create_task(auto_disconnect(vc))
    
    return vc, None

# ================== MUSIC SLASH COMMANDS ==================
@tree.command(name="join", description="Bot tham gia voice channel của bạn")
async def join(interaction: discord.Interaction):
    vc, error = await get_or_connect_vc(interaction, wavelink.Player)
    if error:
        return await interaction.response.send_message(error, ephemeral=True)
        
    await interaction.response.send_message(f"✅ Đã vào kênh **{interaction.user.voice.channel.name}**")

@tree.command(name="leave", description="Bot rời voice channel")
async def leave(interaction: discord.Interaction):
    vc = interaction.guild.voice_client
    if not vc:
        return await interaction.response.send_message("❌ Bot chưa trong voice channel!", ephemeral=True)
    await vc.disconnect()
    await interaction.response.send_message("👋 Bot đã rời kênh!")

@tree.command(name="play", description="Phát nhạc từ YouTube, link, hoặc tìm kiếm")
@app_commands.describe(query="Tên bài hát hoặc link YouTube/SoundCloud/Spotify")
async def play(interaction: discord.Interaction, query: str):
    await interaction.response.defer(thinking=True)
    
    # Kết nối hoặc chuyển sang wavelink.Player
    vc: wavelink.Player | None
    vc, error = await get_or_connect_vc(interaction, wavelink.Player)
    if error:
        return await interaction.followup.send(error)

    # Quyết định loại tìm kiếm (URL hay Search)
    if is_url(query):
        search_query = query
        search_type = "url"
    else:
        search_query = f"ytsearch:{query}"
        search_type = "search"
        
    try:
        results = await wavelink.Pool.fetch_tracks(search_query) 
    except Exception as e:
        return await interaction.followup.send(f"⚠️ Lỗi khi tìm/tải bài hát: {e}")

    if not results:
        return await interaction.followup.send("⚠️ Không tìm thấy bài hát nào.")

    track = results[0]
    await vc.play(track)

    # Tạo Embed
    thumbnail_url = getattr(track, "image", None) or getattr(track, "thumbnail", None)
    if not thumbnail_url and track.uri:
        thumbnail_url = get_youtube_thumbnail(track.uri) 

    embed = discord.Embed(
        title=f"🎶 Đang phát: {track.title}",
        url=track.uri,
        color=discord.Color.green()
    )
    if hasattr(track, "author") and track.author:
        embed.set_author(name=track.author, url=track.uri)
    if thumbnail_url:
        embed.set_thumbnail(url=thumbnail_url)
    
    source_text = "Link đa nguồn" if search_type == "url" else "YouTube"
    embed.set_footer(text=f"Nguồn: {source_text} | Yêu cầu bởi {interaction.user}", icon_url=interaction.user.display_avatar.url)
    
    await interaction.followup.send(embed=embed)


@tree.command(name="pause", description="Tạm dừng nhạc")
async def pause(interaction: discord.Interaction):
    vc = interaction.guild.voice_client
    # Kiểm tra nếu là Wavelink Player để sử dụng lệnh pause/resume
    if not isinstance(vc, wavelink.Player) or not vc.is_playing():
        return await interaction.response.send_message("❌ Không có nhạc stream đang phát!", ephemeral=True)
    await vc.pause()
    await interaction.response.send_message("⏸️ Đã tạm dừng.")

@tree.command(name="resume", description="Tiếp tục nhạc")
async def resume(interaction: discord.Interaction):
    vc = interaction.guild.voice_client
    if not isinstance(vc, wavelink.Player) or not vc.is_paused():
        return await interaction.response.send_message("❌ Không có nhạc stream đang tạm dừng!", ephemeral=True)
    await vc.resume()
    await interaction.response.send_message("▶️ Tiếp tục phát nhạc.")

@tree.command(name="stop", description="Dừng nhạc")
async def stop(interaction: discord.Interaction):
    vc = interaction.guild.voice_client
    if not vc or not vc.is_playing():
        return await interaction.response.send_message("❌ Không có bài đang phát!", ephemeral=True)
    
    # Dừng cả Wavelink và file đính kèm
    vc.stop() 
    await interaction.response.send_message("⏹️ Đã dừng phát nhạc.")


# ================== FILE PLAY SLASH COMMAND (/playfile) ==================

async def play_file_attachment(vc: discord.VoiceClient, url: str):
    """
    Tải và phát file nhạc từ URL đính kèm bằng discord.PCM_AUDIO.
    """
    # Lấy tên file từ URL
    filename = urlparse(url).path.split('/')[-1] or "audio_file"
    temp_file = f"temp_{os.urandom(4).hex()}_{filename}" 
    
    # Dừng nhạc hiện tại
    if vc.is_playing():
        vc.stop()

    try:
        # Tải file
        response = requests.get(url, stream=True)
        response.raise_for_status()
        with open(temp_file, 'wb') as f:
            for chunk in response.iter_content(chunk_size=8192):
                f.write(chunk)

        # Chơi file - Dùng discord.FFmpegPCMAudio
        def after_playing(error):
            # Xóa file tạm thời sau khi kết thúc/lỗi
            if os.path.exists(temp_file):
                os.remove(temp_file)
            if error:
                print(f"Lỗi khi phát file: {error}")

        source = discord.FFmpegPCMAudio(temp_file)
        vc.play(source, after=after_playing)
        return True, filename
    
    except Exception as e:
        print(f"Lỗi khi xử lý file đính kèm: {e}")
        if os.path.exists(temp_file):
            os.remove(temp_file)
        return False, filename

@tree.command(name="playfile", description="Phát file nhạc từ URL (ví dụ: URL file đính kèm)")
@app_commands.describe(url="URL của file nhạc (mp3, wav, v.v.)")
async def playfile_slash(interaction: discord.Interaction, url: str):
    await interaction.response.defer(thinking=True)
    
    # 1. Kết nối hoặc chuyển sang discord.VoiceClient
    vc: discord.VoiceClient | None
    vc, error = await get_or_connect_vc(interaction, discord.VoiceClient)
    if error:
        return await interaction.followup.send(error)

    # 2. Kiểm tra và phát URL
    if not is_url(url) or not any(url.lower().endswith(ext) for ext in ('.mp3', '.wav', '.flac', '.ogg')):
        return await interaction.followup.send("⚠️ URL không hợp lệ hoặc không phải là định dạng file nhạc được hỗ trợ (.mp3, .wav, v.v.)")
    
    success, filename = await play_file_attachment(vc, url)

    if success:
        await interaction.followup.send(f"🎧 Đang phát file: **{filename}**.")
    else:
        await interaction.followup.send("⚠️ Lỗi khi phát file nhạc.")


# ================== ROBLOX COMMAND ==================
async def get_roblox_info(username: str):
    url_id = 'https://users.roblox.com/v1/usernames/users'
    payload_id = {"usernames":[username],"excludeBannedUsers":True}
    try:
        data_id = requests.post(url_id,json=payload_id).json()
    except:
        return "Lỗi kết nối API Roblox"
    if not data_id.get('data'): return None
    user_id = data_id['data'][0]['id']

    data_profile = requests.get(f'https://users.roblox.com/v1/users/{user_id}').json()
    presence_info = requests.post('https://presence.roblox.com/v1/presence/users', json={"userIds":[user_id]}).json()['userPresences'][0]
    if presence_info['userPresenceType']==2:
        game_status = f"🎮 Đang chơi: **{presence_info['lastLocation']}**"
    elif presence_info['userPresenceType']==1:
        game_status = "🟢 Trực tuyến trên trang web Roblox"
    else:
        game_status = "⚫ Ngoại tuyến"

    avatar_url = requests.get(f'https://thumbnails.roblox.com/v1/users/avatar-headshot?userIds={user_id}&size=150x150&format=Png&isCircular=false').json()['data'][0]['imageUrl']

    return {
        'id': user_id,
        'username': data_profile.get('name','N/A'),
        'display_name': data_profile.get('displayName','N/A'),
        'bio': data_profile.get('description','Không có mô tả.'),
        'game_status': game_status,
        'avatar_url': avatar_url
    }

@tree.command(name="roblox", description="Tra cứu Roblox user")
@app_commands.describe(username="Tên người dùng Roblox cần tra cứu")
async def roblox(interaction: discord.Interaction, username: str):
    await interaction.response.defer()
    info = await get_roblox_info(username)
    if info is None:
        return await interaction.followup.send(f"Không tìm thấy người dùng **{username}**")
    if isinstance(info,str):
        return await interaction.followup.send(f"Lỗi API: {info}")

    embed = discord.Embed(
        title=f"⭐ Roblox: {info['display_name']}",
        url=f"https://www.roblox.com/users/{info['id']}/profile",
        color=discord.Color.blue()
    )
    embed.set_thumbnail(url=info['avatar_url'])
    embed.add_field(name="Username", value=f"`{info['username']}`", inline=True)
    embed.add_field(name="User ID", value=f"`{info['id']}`", inline=True)
    embed.add_field(name="Trạng thái", value=info['game_status'], inline=False)
    bio_text = info['bio'][:300] + ("..." if len(info['bio'])>300 else "")
    embed.add_field(name="Bio", value=bio_text or "Không có mô tả.", inline=False)
    embed.set_footer(text=f"Yêu cầu bởi {interaction.user}", icon_url=interaction.user.display_avatar.url)

    await interaction.followup.send(embed=embed)

# ================== UTILITY COMMANDS ==================
@tree.command(name="send", description="Gửi tin nhắn đến một kênh cụ thể")
@app_commands.describe(channel="Kênh cần gửi tin nhắn", message="Nội dung tin nhắn cần gửi")
async def send(interaction: discord.Interaction, channel: discord.TextChannel, message: str):
    # Chỉ cho phép admin hoặc người có quyền quản lý server
    if not interaction.user.guild_permissions.administrator:
        return await interaction.response.send_message("❌ Bạn không có quyền sử dụng lệnh này!", ephemeral=True)
    
    try:
        await channel.send(message)
        await interaction.response.send_message(f"✅ Đã gửi tin nhắn đến kênh {channel.mention}", ephemeral=True)
    except Exception as e:
        await interaction.response.send_message(f"⚠️ Lỗi khi gửi tin: {e}", ephemeral=True)


# ================== ON_READY ==================
@bot.event
async def on_ready():
    print(f"✅ Bot đã đăng nhập: {bot.user} (ID: {bot.user.id})")
    # Kết nối Lavalink Node
    if not wavelink.Pool.nodes:
        node = wavelink.Node(uri=LAVALINK_URI, password=LAVALINK_PASSWORD)
        await wavelink.Pool.connect(nodes=[node], client=bot)
        print("🎵 Lavalink node đã kết nối!")
    try:
        # Sync slash commands
        synced = await tree.sync()
        print(f"🌐 Slash commands đã sync ({len(synced)} lệnh).")
    except Exception as e:
        print(f"⚠️ Lỗi sync slash commands: {e}")

# ================== AUTO DISCONNECT ==================
async def auto_disconnect(vc: discord.VoiceClient, timeout: int = 300):
    """Nếu voice channel không còn nhạc Wavelink, tự động rời sau timeout giây (mặc định 5 phút)."""
    # Chỉ áp dụng cho wavelink.Player
    if not isinstance(vc, wavelink.Player):
        # Nếu là VoiceClient bình thường thì chỉ đợi timeout
        return await asyncio.sleep(timeout)

    # Đợi timeout
    await asyncio.sleep(timeout)

    # Kiểm tra lại trạng thái player
    # 'playing' và 'paused' là properties mới trong wavelink Player
    if getattr(vc, "playing", False) or getattr(vc, "paused", False):
        return  # còn nhạc/dừng tạm thì không rời

    # Nếu đã kết nối mà không còn nhạc thì disconnect
    if vc.is_connected():
        await vc.disconnect()
        print(f"🔹 Bot đã rời voice channel do không còn nhạc sau {timeout} giây.")
# ================== AUTO DELETE MESSAGES ==================
AUTO_DELETE_CHANNEL = int(os.getenv("AUTO_DELETE_CHANNEL", "0"))

@bot.event
async def on_message(message: discord.Message):
    # ⚙️ Duy trì slash & prefix commands
    await bot.process_commands(message)

    # ⚠️ Nếu chưa đặt AUTO_DELETE_CHANNEL hoặc = 0 thì bỏ qua
    if AUTO_DELETE_CHANNEL == 0:
        return

    # ✅ Chỉ xử lý tin trong kênh được cấu hình
    if message.channel.id == AUTO_DELETE_CHANNEL:
        # Bot sẽ xóa tin nhắn của mọi người (kể cả bot) sau 30 phút
        await asyncio.sleep(1800) 
        try:
            await message.delete()
        except discord.NotFound:
            pass 
        except discord.Forbidden:
            pass
        except Exception:
            pass

# ================== RUN BOT ==================
bot.run(TOKEN)

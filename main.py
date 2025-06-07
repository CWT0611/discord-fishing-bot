import discord
from discord.ext import commands
import json
import random
import asyncio
from flask import Flask, jsonify, request
import threading
import os
from datetime import datetime

# 嘗試載入 python-dotenv，如果沒有安裝就跳過
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

# Flask 設定
app = Flask(__name__)

# Discord Bot 設定
intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix='/', intents=intents)

# 遊戲資料
game_data = {
    'users': {},
    'fish_data': {
        'common': {
            '小魚': {'weight_range': (0.1, 0.5), 'price_per_kg': 10},
            '鯉魚': {'weight_range': (0.3, 1.2), 'price_per_kg': 15},
            '草魚': {'weight_range': (0.5, 1.5), 'price_per_kg': 12}
        },
        'rare': {
            '鯛魚': {'weight_range': (0.8, 2.0), 'price_per_kg': 30},
            '鱸魚': {'weight_range': (1.0, 2.5), 'price_per_kg': 35},
            '石斑魚': {'weight_range': (1.2, 3.0), 'price_per_kg': 40}
        },
        'epic': {
            '鮭魚': {'weight_range': (2.0, 4.0), 'price_per_kg': 60},
            '鮪魚': {'weight_range': (3.0, 6.0), 'price_per_kg': 80},
            '旗魚': {'weight_range': (4.0, 8.0), 'price_per_kg': 100}
        },
        'legendary': {
            '龍魚': {'weight_range': (5.0, 10.0), 'price_per_kg': 200},
            '鯊魚': {'weight_range': (8.0, 15.0), 'price_per_kg': 250},
            '黃金魚': {'weight_range': (1.0, 3.0), 'price_per_kg': 500}
        }
    },
    'items': {
        '基本魚竿': {'price': 0, 'catch_bonus': 1.0, 'rare_bonus': 0.0},
        '中級魚竿': {'price': 500, 'catch_bonus': 1.2, 'rare_bonus': 0.1},
        '高級魚竿': {'price': 1500, 'catch_bonus': 1.5, 'rare_bonus': 0.2},
        '傳說魚竿': {'price': 5000, 'catch_bonus': 2.0, 'rare_bonus': 0.3},
        '魚餌': {'price': 50, 'catch_bonus': 1.1, 'rare_bonus': 0.05}
    },
    'rarity_rates': {
        'common': 0.6,
        'rare': 0.25,
        'epic': 0.12,
        'legendary': 0.03
    }
}

def get_user_data(user_id):
    """獲取或創建用戶資料"""
    user_id = str(user_id)
    if user_id not in game_data['users']:
        game_data['users'][user_id] = {
            'money': 100,
            'items': {'基本魚竿': 1},
            'current_rod': '基本魚竿',
            'fish_caught': {},
            'total_catches': 0
        }
    return game_data['users'][user_id]

def calculate_catch_probability(user_data):
    """計算釣魚成功率和稀有度加成"""
    rod = user_data['current_rod']
    catch_bonus = game_data['items'][rod]['catch_bonus']
    rare_bonus = game_data['items'][rod]['rare_bonus']
    
    # 魚餌加成
    if '魚餌' in user_data['items'] and user_data['items']['魚餌'] > 0:
        catch_bonus *= game_data['items']['魚餌']['catch_bonus']
        rare_bonus += game_data['items']['魚餌']['rare_bonus']
        user_data['items']['魚餌'] -= 1
        if user_data['items']['魚餌'] <= 0:
            del user_data['items']['魚餌']
    
    return catch_bonus, rare_bonus

def determine_fish_rarity(rare_bonus):
    """決定魚的稀有度"""
    rates = game_data['rarity_rates'].copy()
    
    # 應用稀有度加成
    rates['legendary'] += rare_bonus * 0.3
    rates['epic'] += rare_bonus * 0.4
    rates['rare'] += rare_bonus * 0.3
    
    # 重新標準化
    total = sum(rates.values())
    for rarity in rates:
        rates[rarity] /= total
    
    rand = random.random()
    cumulative = 0
    
    for rarity, rate in rates.items():
        cumulative += rate
        if rand <= cumulative:
            return rarity
    
    return 'common'

def save_data():
    """保存遊戲資料"""
    try:
        with open('game_data.json', 'w', encoding='utf-8') as f:
            json.dump(game_data, f, ensure_ascii=False, indent=2)
        return True
    except:
        return False

def load_data():
    """載入遊戲資料"""
    global game_data
    try:
        with open('game_data.json', 'r', encoding='utf-8') as f:
            loaded_data = json.load(f)
            game_data.update(loaded_data)
        return True
    except:
        return False

# Discord Bot 指令
@bot.event
async def on_ready():
    print(f'{bot.user} 已連線!')
    load_data()

@bot.command(name='game')
async def game_help(ctx):
    """遊戲指令說明"""
    embed = discord.Embed(title="🎣 釣魚遊戲指令", color=0x00ff00)
    
    commands_text = """
    `/fish` - 開始釣魚
    `/fish item` - 切換釣魚道具
    `/shop` - 查看商店
    `/bag` - 查看背包和金錢
    `/new` - 建立新遊戲（重置資料）
    `/load` - 載入存檔資料
    `/save` - 保存當前資料
    
    **稀有度等級:**
    🟢 普通 (Common)
    🔵 稀有 (Rare) 
    🟣 史詩 (Epic)
    🟡 傳說 (Legendary)
    
    **釣魚系統:**
    - 根據魚的稀有度和重量獲得金錢
    - 使用更好的魚竿提高成功率和稀有魚機率
    - 魚餌可以提供額外加成
    """
    
    embed.add_field(name="指令列表", value=commands_text, inline=False)
    await ctx.send(embed=embed)

@bot.command(name='fish')
async def fish(ctx, action=None):
    """釣魚指令"""
    user_data = get_user_data(ctx.author.id)
    
    if action == 'item':
        # 切換道具
        items = [item for item in user_data['items'] if item.endswith('魚竿')]
        if not items:
            await ctx.send("❌ 你沒有任何魚竿!")
            return
        
        embed = discord.Embed(title="🎣 選擇釣魚道具", color=0x0099ff)
        for i, item in enumerate(items, 1):
            status = "✅ 使用中" if item == user_data['current_rod'] else ""
            embed.add_field(
                name=f"{i}. {item} {status}",
                value=f"數量: {user_data['items'][item]}",
                inline=False
            )
        
        embed.set_footer(text="請輸入數字選擇道具")
        await ctx.send(embed=embed)
        
        def check(m):
            return m.author == ctx.author and m.channel == ctx.channel
        
        try:
            msg = await bot.wait_for('message', check=check, timeout=30.0)
            choice = int(msg.content) - 1
            if 0 <= choice < len(items):
                user_data['current_rod'] = items[choice]
                await ctx.send(f"✅ 已切換到 {items[choice]}!")
            else:
                await ctx.send("❌ 無效的選擇!")
        except (ValueError, asyncio.TimeoutError):
            await ctx.send("❌ 無效的輸入或超時!")
        return
    
    # 釣魚邏輯
    catch_bonus, rare_bonus = calculate_catch_probability(user_data)
    
    # 釣魚成功率 (70% 基礎 + 道具加成)
    success_rate = min(0.95, 0.7 * catch_bonus)
    
    embed = discord.Embed(title="🎣 釣魚中...", color=0xffff00)
    embed.add_field(name="使用道具", value=user_data['current_rod'], inline=True)
    message = await ctx.send(embed=embed)
    
    await asyncio.sleep(2)  # 等待效果
    
    if random.random() > success_rate:
        embed = discord.Embed(title="💔 釣魚失敗", color=0xff0000)
        embed.add_field(name="結果", value="什麼都沒釣到...", inline=False)
        await message.edit(embed=embed)
        return
    
    # 成功釣到魚
    rarity = determine_fish_rarity(rare_bonus)
    fish_name = random.choice(list(game_data['fish_data'][rarity].keys()))
    fish_info = game_data['fish_data'][rarity][fish_name]
    
    weight = round(random.uniform(*fish_info['weight_range']), 2)
    price = int(weight * fish_info['price_per_kg'])
    
    # 更新用戶資料
    user_data['money'] += price
    user_data['total_catches'] += 1
    if fish_name not in user_data['fish_caught']:
        user_data['fish_caught'][fish_name] = 0
    user_data['fish_caught'][fish_name] += 1
    
    # 稀有度顏色
    rarity_colors = {
        'common': 0x808080,
        'rare': 0x0080ff,
        'epic': 0x8000ff,
        'legendary': 0xffd700
    }
    
    rarity_emojis = {
        'common': '🟢',
        'rare': '🔵',
        'epic': '🟣',
        'legendary': '🟡'
    }
    
    embed = discord.Embed(title="🎉 釣魚成功!", color=rarity_colors[rarity])
    embed.add_field(name="魚類", value=f"{rarity_emojis[rarity]} {fish_name}", inline=True)
    embed.add_field(name="重量", value=f"{weight} kg", inline=True)
    embed.add_field(name="獲得金錢", value=f"💰 {price}", inline=True)
    embed.add_field(name="目前金錢", value=f"💰 {user_data['money']}", inline=True)
    
    await message.edit(embed=embed)
    save_data()

@bot.command(name='shop')
async def shop(ctx):
    """商店"""
    embed = discord.Embed(title="🏪 釣魚用品商店", color=0x00ff00)
    
    for i, (item, info) in enumerate(game_data['items'].items(), 1):
        embed.add_field(
            name=f"{i}. {item}",
            value=f"價格: 💰{info['price']}\n成功率加成: {info['catch_bonus']}x\n稀有度加成: +{info['rare_bonus']}",
            inline=True
        )
    
    embed.set_footer(text="輸入數字購買道具")
    await ctx.send(embed=embed)
    
    def check(m):
        return m.author == ctx.author and m.channel == ctx.channel
    
    try:
        msg = await bot.wait_for('message', check=check, timeout=30.0)
        choice = int(msg.content) - 1
        items = list(game_data['items'].items())
        
        if 0 <= choice < len(items):
            item_name, item_info = items[choice]
            user_data = get_user_data(ctx.author.id)
            
            if user_data['money'] >= item_info['price']:
                user_data['money'] -= item_info['price']
                if item_name not in user_data['items']:
                    user_data['items'][item_name] = 0
                user_data['items'][item_name] += 1
                save_data()
                await ctx.send(f"✅ 成功購買 {item_name}!")
            else:
                await ctx.send(f"❌ 金錢不足! 需要 💰{item_info['price']}")
        else:
            await ctx.send("❌ 無效的選擇!")
    except (ValueError, asyncio.TimeoutError):
        await ctx.send("❌ 無效的輸入或超時!")

@bot.command(name='bag')
async def bag(ctx):
    """查看背包"""
    user_data = get_user_data(ctx.author.id)
    
    embed = discord.Embed(title="🎒 背包", color=0x9932cc)
    embed.add_field(name="💰 金錢", value=str(user_data['money']), inline=True)
    embed.add_field(name="🎣 當前魚竿", value=user_data['current_rod'], inline=True)
    embed.add_field(name="📊 總釣魚次數", value=str(user_data['total_catches']), inline=True)
    
    # 道具列表
    items_text = ""
    for item, count in user_data['items'].items():
        items_text += f"{item}: {count}\n"
    
    if items_text:
        embed.add_field(name="🛠️ 道具", value=items_text, inline=False)
    
    # 釣到的魚
    if user_data['fish_caught']:
        fish_text = ""
        for fish, count in user_data['fish_caught'].items():
            fish_text += f"{fish}: {count}\n"
        embed.add_field(name="🐟 釣到的魚", value=fish_text, inline=False)
    
    await ctx.send(embed=embed)

@bot.command(name='load')
async def load_command(ctx):
    """載入資料"""
    if load_data():
        await ctx.send("✅ 資料載入成功!")
    else:
        await ctx.send("❌ 資料載入失敗!")

@bot.command(name='save')
async def save_command(ctx):
    """保存資料並回傳"""
    if save_data():
        try:
            with open('game_data.json', 'r', encoding='utf-8') as f:
                content = f.read()
            
            # 如果檔案太大，分割傳送
            if len(content) > 1900:
                await ctx.send("📄 遊戲資料已保存，檔案內容:")
                await ctx.send(f"```json\n{content[:1900]}```")
                if len(content) > 1900:
                    await ctx.send(f"```json\n{content[1900:]}```")
            else:
                await ctx.send(f"✅ 遊戲資料已保存!\n```json\n{content}```")
        except:
            await ctx.send("✅ 資料保存成功，但無法顯示檔案內容")
    else:
        await ctx.send("❌ 資料保存失敗!")

@bot.command(name='new')
async def new_game(ctx):
    """建立新遊戲（重置玩家資料）"""
    user_data = get_user_data(ctx.author.id)
    
    # 顯示確認訊息
    embed = discord.Embed(
        title="⚠️ 建立新遊戲", 
        description="這將會重置你的所有遊戲資料，包括：",
        color=0xff6600
    )
    
    reset_info = f"""
    💰 金錢: {user_data['money']} → 100
    🎣 道具: {len(user_data['items'])} 個 → 1 個（基本魚竿）
    🐟 釣魚記錄: {user_data['total_catches']} 次 → 0
    📊 魚類收藏: {len(user_data['fish_caught'])} 種 → 0
    
    ⚠️ **此操作無法復原！**
    """
    
    embed.add_field(name="將會重置的資料", value=reset_info, inline=False)
    embed.add_field(name="確認操作", value="輸入 `確認` 或 `confirm` 來建立新遊戲\n輸入其他任何內容取消", inline=False)
    embed.set_footer(text="30秒內未回應將自動取消")
    
    await ctx.send(embed=embed)
    
    def check(m):
        return m.author == ctx.author and m.channel == ctx.channel
    
    try:
        msg = await bot.wait_for('message', check=check, timeout=30.0)
        user_input = msg.content.lower().strip()
        
        if user_input in ['確認', 'confirm', '确认']:
            # 重置玩家資料
            game_data['users'][str(ctx.author.id)] = {
                'money': 100,
                'items': {'基本魚竿': 1},
                'current_rod': '基本魚竿',
                'fish_caught': {},
                'total_catches': 0
            }
            
            # 保存資料
            save_data()
            
            # 成功訊息
            success_embed = discord.Embed(
                title="🎉 新遊戲建立成功!", 
                color=0x00ff00
            )
            success_embed.add_field(
                name="初始狀態", 
                value="💰 金錢: 100\n🎣 道具: 基本魚竿 x1\n🐟 釣魚記錄: 0", 
                inline=False
            )
            success_embed.add_field(
                name="開始遊戲", 
                value="使用 `/fish` 開始你的釣魚冒險！\n使用 `/game` 查看所有指令", 
                inline=False
            )
            
            await ctx.send(embed=success_embed)
            
        else:
            # 取消操作
            cancel_embed = discord.Embed(
                title="❌ 已取消建立新遊戲", 
                description="你的遊戲資料保持不變",
                color=0x808080
            )
            await ctx.send(embed=cancel_embed)
            
    except asyncio.TimeoutError:
        timeout_embed = discord.Embed(
            title="⏰ 操作超時", 
            description="建立新遊戲已取消，你的資料保持不變",
            color=0x808080
        )
        await ctx.send(embed=timeout_embed)

# Flask 路由 (用於 Render 部署)
@app.route('/')
def home():
    return jsonify({
        "status": "Bot is running",
        "timestamp": datetime.now().isoformat()
    })

@app.route('/health')
def health():
    return jsonify({"status": "healthy"})

@app.route('/data')
def get_data():
    return jsonify(game_data)

def run_flask():
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)

if __name__ == '__main__':
    # 啟動 Flask 服務器
    flask_thread = threading.Thread(target=run_flask)
    flask_thread.daemon = True
    flask_thread.start()
    
    # 啟動 Discord Bot
    BOT_TOKEN = os.environ.get('DISCORD_BOT_TOKEN')
    if BOT_TOKEN:
        bot.run(BOT_TOKEN)
    else:
        print("請設定 DISCORD_BOT_TOKEN 環境變數")
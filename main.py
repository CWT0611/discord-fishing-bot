import discord
from discord.ext import commands
from discord import app_commands
import json
import random
import asyncio
from flask import Flask, jsonify, request
import threading
import os
from datetime import datetime
import io

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
intents.message_content = True # 允許讀取訊息內容以支援傳統指令，但我們主要用斜線指令
bot = commands.Bot(command_prefix='/', intents=intents) # 傳統指令前綴，但主要使用斜線指令

# 遊戲資料 (全局變數，從文件載入或初始化)
game_data = {
    'users': {},
    'fish_data': {
        'common': {
            '小魚': {'weight_range': (0.1, 0.5), 'price_per_kg': 10, 'emoji': '🐠'},
            '鯉魚': {'weight_range': (0.3, 1.2), 'price_per_kg': 15, 'emoji': '🐟'},
            '草魚': {'weight_range': (0.5, 1.5), 'price_per_kg': 12, 'emoji': '🐡'}
        },
        'rare': {
            '鯛魚': {'weight_range': (0.8, 2.0), 'price_per_kg': 30, 'emoji': '🐡'},
            '鱸魚': {'weight_range': (1.0, 2.5), 'price_per_kg': 35, 'emoji': '🐟'},
            '石斑魚': {'weight_range': (1.2, 3.0), 'price_per_kg': 40, 'emoji': '🦈'}
        },
        'epic': {
            '鮭魚': {'weight_range': (2.0, 4.0), 'price_per_kg': 60, 'emoji': '🍣'},
            '鮪魚': {'weight_range': (3.0, 6.0), 'price_per_kg': 80, 'emoji': '🐟'},
            '旗魚': {'weight_range': (4.0, 8.0), 'price_per_kg': 100, 'emoji': '🗡️'}
        },
        'legendary': {
            '龍魚': {'weight_range': (5.0, 10.0), 'price_per_kg': 200, 'emoji': '🐉'},
            '鯊魚': {'weight_range': (8.0, 15.0), 'price_per_kg': 250, 'emoji': '🦈'},
            '黃金魚': {'weight_range': (1.0, 3.0), 'price_per_kg': 500, 'emoji': '🌟'}
        },
        'junk': { # 新增雜物，例如破鞋
            '破鞋': {'weight_range': (0.1, 0.5), 'price_per_kg': 1, 'emoji': '👟'}
        }
    },
    'items': {
        '基本魚竿': {'price': 0, 'catch_bonus': 1.0, 'rare_bonus': 0.0, 'description': '最初始的魚竿，沒有任何加成。'},
        '中級魚竿': {'price': 500, 'catch_bonus': 1.2, 'rare_bonus': 0.1, 'description': '提高釣魚成功率和釣到稀有魚的機率。'},
        '高級魚竿': {'price': 1500, 'catch_bonus': 1.5, 'rare_bonus': 0.2, 'description': '顯著提高釣魚成功率和釣到稀有魚的機率。'},
        '傳說魚竿': {'price': 5000, 'catch_bonus': 2.0, 'rare_bonus': 0.3, 'description': '大幅提高釣魚成功率和釣到傳說魚的機率。'},
        '魚餌': {'price': 50, 'catch_bonus': 1.1, 'rare_bonus': 0.05, 'description': '一次性消耗品，使用後會略微提高釣魚成功率和稀有度機率。'}
    },
    'rarity_rates': {
        'common': 0.6,
        'rare': 0.25,
        'epic': 0.12,
        'legendary': 0.03,
        'junk': 0.1 # 釣到垃圾的機率
    }
}

# --- 輔助函數：資料儲存與載入 ---
def get_user_data(user_id):
    """獲取或創建用戶資料"""
    user_id = str(user_id)
    if user_id not in game_data['users']:
        game_data['users'][user_id] = {
            'money': 100,
            'items': {'基本魚竿': 1}, # 初始化時只有基本魚竿
            'current_rod': '基本魚竿',
            'fish_caught': {}, # 記錄釣到的魚的種類和數量
            'total_catches': 0
        }
    return game_data['users'][user_id]

def save_game_data():
    """保存遊戲資料到檔案"""
    try:
        with open('game_data.json', 'w', encoding='utf-8') as f:
            json.dump(game_data, f, ensure_ascii=False, indent=2)
        print("遊戲資料已保存。")
        return True
    except Exception as e:
        print(f"保存遊戲資料失敗: {e}")
        return False

def load_game_data():
    """從檔案載入遊戲資料"""
    global game_data
    try:
        if os.path.exists('game_data.json'):
            with open('game_data.json', 'r', encoding='utf-8') as f:
                loaded_data = json.load(f)
                # 僅更新動態部分，保留靜態遊戲設定
                game_data['users'] = loaded_data.get('users', {})
                # 可以選擇性地載入其他全局設定，如果它們是動態的
                print("遊戲資料載入成功。")
            return True
        else:
            print("game_data.json 不存在，初始化新資料。")
            # 如果文件不存在，確保 game_data['users'] 依然是空的字典
            game_data['users'] = {}
            save_game_data() # 創建一個空的 game_data.json
            return True
    except Exception as e:
        print(f"載入遊戲資料失敗: {e}")
        return False

# --- 遊戲邏輯函數 ---
def calculate_catch_probability(user_data):
    """計算釣魚成功率和稀有度加成"""
    rod = user_data['current_rod']
    # 確保魚竿存在於 game_data['items']，否則使用預設值
    rod_info = game_data['items'].get(rod, game_data['items']['基本魚竿'])

    catch_bonus = rod_info['catch_bonus']
    rare_bonus = rod_info['rare_bonus']

    # 檢查魚餌加成
    if '魚餌' in user_data['items'] and user_data['items']['魚餌'] > 0:
        bait_info = game_data['items']['魚餌']
        catch_bonus *= bait_info['catch_bonus']
        rare_bonus += bait_info['rare_bonus']
        user_data['items']['魚餌'] -= 1
        if user_data['items']['魚餌'] <= 0:
            del user_data['items']['魚餌'] # 魚餌用完移除
        print(f"DEBUG: 使用魚餌，剩餘 {user_data['items'].get('魚餌', 0)} 個") # 檢查魚餌消耗

    return catch_bonus, rare_bonus

def determine_fish_rarity(rare_bonus):
    """決定魚的稀有度，考慮稀有度加成和釣到垃圾的機率"""
    rates = game_data['rarity_rates'].copy()

    # 應用稀有度加成，同時確保稀有度機率之和不超過 1
    # 這裡可以根據稀有度加成點數，按比例分配到更高稀有度的機率上
    # 並從普通和垃圾機率中扣除
    total_boost = rare_bonus
    if total_boost > 0:
        boost_to_legendary = total_boost * 0.4 # 40% 傳說
        boost_to_epic = total_boost * 0.3 # 30% 史詩
        boost_to_rare = total_boost * 0.2 # 20% 稀有
        boost_to_common_or_junk = total_boost * 0.1 # 10% 剩餘分配

        # 增加高稀有度的機率
        rates['legendary'] += boost_to_legendary
        rates['epic'] += boost_to_epic
        rates['rare'] += boost_to_rare

        # 從 common 或 junk 中扣除
        # 先嘗試從 common 扣除，如果 common 不夠再從 junk 扣
        deduct_from_common = min(rates['common'], total_boost * 0.7) # 假設主要從common扣
        rates['common'] -= deduct_from_common
        total_boost -= deduct_from_common

        if total_boost > 0:
            deduct_from_junk = min(rates['junk'], total_boost)
            rates['junk'] -= deduct_from_junk
            total_boost -= deduct_from_junk


    # 確保所有機率總和為 1
    total_sum = sum(rates.values())
    if total_sum != 0: # 避免除以零
        for rarity in rates:
            rates[rarity] /= total_sum

    rand = random.random()
    cumulative = 0

    for rarity, rate in rates.items():
        cumulative += rate
        if rand <= cumulative:
            return rarity

    return 'common' # 預設回傳 common

# --- Discord 機器人事件 ---
@bot.event
async def on_ready():
    print(f'{bot.user} 已連線!')
    load_game_data() # 機器人啟動時自動載入資料

    # 同步斜線指令到 Discord
    try:
        synced_commands = await bot.tree.sync()
        print(f"已同步 {len(synced_commands)} 個斜線指令。")
    except Exception as e:
        print(f"同步指令失敗: {e}")

# --- 斜線指令定義 ---

@bot.tree.command(name='game', description='顯示所有可用的遊戲指令和遊戲說明。')
async def game_command(interaction: discord.Interaction):
    """遊戲指令說明"""
    embed = discord.Embed(title="🎣 釣魚遊戲指令", color=0x00ff00)

    commands_text = """
    `/fish` - 開始釣魚
    `/fish_item` - 切換釣魚道具（魚竿）
    `/shop` - 查看商店
    `/buy <物品名稱>` - 從商店購買物品
    `/bag` - 查看背包、金錢和釣到的魚
    `/new_game` - 建立新遊戲（重置你的資料）
    `/load` - 上傳你的遊戲進度 JSON 檔案，繼續之前的進度
    `/save` - 將你的遊戲進度保存為 JSON 檔案，以便下載
    """

    game_info_text = """
    **釣魚系統：**
    - 根據魚的稀有度和重量獲得金錢。
    - 使用更好的魚竿可以提高釣魚成功率和稀有魚的機率。
    - 魚餌是一次性消耗品，能提供額外加成。
    **稀有度等級:**
    🟢 普通 (Common)
    🔵 稀有 (Rare)
    🟣 史詩 (Epic)
    🟡 傳說 (Legendary)
    ⚫ 垃圾 (Junk)
    """

    embed.add_field(name="指令列表", value=commands_text, inline=False)
    embed.add_field(name="遊戲說明", value=game_info_text, inline=False)
    await interaction.response.send_message(embed=embed, ephemeral=True) # 通常指令列表只給發送者看

@bot.tree.command(name='new_game', description='開始一個新遊戲並重置你的進度。')
async def new_game_command(interaction: discord.Interaction):
    """建立新遊戲（重置玩家資料）"""
    user_id = str(interaction.user.id)
    user_data_before_reset = get_user_data(user_id) # 獲取重置前的資料以顯示

    # 顯示確認訊息
    embed = discord.Embed(
        title="⚠️ 建立新遊戲確認",
        description="這將會重置你的所有遊戲資料。**此操作無法復原！**",
        color=0xff6600
    )

    reset_info = f"""
    💰 金錢: {user_data_before_reset['money']} → 100
    🎣 道具數量: {sum(user_data_before_reset['items'].values())} 個 → 1 個（基本魚竿）
    📊 總釣魚次數: {user_data_before_reset['total_catches']} 次 → 0
    🐟 魚類收藏: {len(user_data_before_reset['fish_caught'])} 種 → 0

    請輸入 `確認重置` 來建立新遊戲，輸入其他任何內容則取消。
    """
    embed.add_field(name="將會重置的資料概覽", value=reset_info, inline=False)
    embed.set_footer(text="你有 30 秒時間回應。")

    await interaction.response.send_message(embed=embed, ephemeral=True)

    def check(m):
        return m.author == interaction.user and m.channel == interaction.channel

    try:
        msg = await bot.wait_for('message', check=check, timeout=30.0)
        user_input = msg.content.lower().strip()

        if user_input == '確認重置':
            # 重置玩家資料
            game_data['users'][user_id] = {
                'money': 100,
                'items': {'基本魚竿': 1},
                'current_rod': '基本魚竿',
                'fish_caught': {},
                'total_catches': 0
            }
            save_game_data() # 重置後自動保存

            success_embed = discord.Embed(
                title="🎉 新遊戲建立成功!",
                description="你的遊戲資料已重置為初始狀態。",
                color=0x00ff00
            )
            success_embed.add_field(name="初始狀態", value="💰 金錢: 100\n🎣 道具: 基本魚竿 x1\n🐟 釣魚記錄: 0", inline=False)
            success_embed.add_field(name="開始遊戲", value="使用 `/fish` 開始你的釣魚冒險！\n使用 `/game` 查看所有指令。", inline=False)
            await interaction.followup.send(embed=success_embed, ephemeral=False)
        else:
            cancel_embed = discord.Embed(
                title="❌ 已取消建立新遊戲",
                description="你的遊戲資料保持不變。",
                color=0x808080
            )
            await interaction.followup.send(embed=cancel_embed, ephemeral=True)

    except asyncio.TimeoutError:
        timeout_embed = discord.Embed(
            title="⏰ 操作超時",
            description="建立新遊戲已取消，你的資料保持不變。",
            color=0x808080
        )
        await interaction.followup.send(embed=timeout_embed, ephemeral=True)
    except Exception as e:
        error_embed = discord.Embed(
            title="發生錯誤",
            description=f"在建立新遊戲時發生錯誤: {e}",
            color=0xff0000
        )
        await interaction.followup.send(embed=error_embed, ephemeral=True)


@bot.tree.command(name='fish', description='開始釣魚！')
async def fish_command(interaction: discord.Interaction):
    """釣魚指令"""
    user_id = str(interaction.user.id)
    user_data = get_user_data(user_id)

    # 確保用戶有魚竿
    if not user_data['items'] or not user_data['current_rod'] in user_data['items']:
        await interaction.response.send_message("❌ 你沒有任何魚竿！請先到 `/shop` 購買。", ephemeral=True)
        return

    catch_bonus, rare_bonus = calculate_catch_probability(user_data)

    # 釣魚成功率 (70% 基礎 + 道具加成，最高 95%)
    success_rate = min(0.95, 0.7 * catch_bonus)

    embed = discord.Embed(title="🎣 釣魚中...", color=0xffff00)
    embed.add_field(name="使用道具", value=user_data['current_rod'], inline=True)
    if '魚餌' in user_data['items'] and user_data['items']['魚餌'] > 0:
        embed.add_field(name="使用魚餌", value="是", inline=True)
    message = await interaction.response.send_message(embed=embed, ephemeral=False) # 釣魚結果通常公開

    await asyncio.sleep(2) # 模擬釣魚等待時間

    if random.random() > success_rate:
        embed = discord.Embed(title="💔 釣魚失敗", color=0xff0000)
        embed.add_field(name="結果", value="什麼都沒釣到...", inline=False)
        await interaction.edit_original_response(embed=embed)
        save_game_data() # 即使失敗也保存（魚餌可能消耗）
        return

    # 成功釣到魚
    rarity = determine_fish_rarity(rare_bonus)
    # 確保選擇的稀有度有魚
    if not game_data['fish_data'].get(rarity):
        rarity = 'common' # fallback
    fish_name = random.choice(list(game_data['fish_data'][rarity].keys()))
    fish_info = game_data['fish_data'][rarity][fish_name]

    weight = round(random.uniform(*fish_info['weight_range']), 2)
    price = int(weight * fish_info['price_per_kg'])
    emoji = fish_info.get('emoji', '🐟')

    # 更新用戶資料
    user_data['money'] += price
    user_data['total_catches'] += 1
    if fish_name not in user_data['fish_caught']:
        user_data['fish_caught'][fish_name] = 0
    user_data['fish_caught'][fish_name] += 1

    # 稀有度顏色和表情
    rarity_colors = {
        'common': 0x808080, # 灰色
        'rare': 0x0080ff,   # 藍色
        'epic': 0x8000ff,   # 紫色
        'legendary': 0xffd700, # 金色
        'junk': 0x404040    # 深灰色
    }

    rarity_emojis = {
        'common': '🟢',
        'rare': '🔵',
        'epic': '🟣',
        'legendary': '🟡',
        'junk': '⚫'
    }

    embed = discord.Embed(title="🎉 釣魚成功!", color=rarity_colors[rarity])
    embed.add_field(name="魚類", value=f"{rarity_emojis[rarity]} {fish_name} {emoji}", inline=True)
    embed.add_field(name="重量", value=f"{weight} kg", inline=True)
    embed.add_field(name="獲得金錢", value=f"💰 {price}", inline=True)
    embed.add_field(name="目前金錢", value=f"💰 {user_data['money']}", inline=True)

    await interaction.edit_original_response(embed=embed)
    save_game_data() # 成功釣魚後保存

@bot.tree.command(name='fish_item', description='切換你的釣魚道具（魚竿）。')
async def fish_item_command(interaction: discord.Interaction):
    """切換釣魚道具"""
    user_data = get_user_data(interaction.user.id)

    # 篩選出所有魚竿類型的道具
    rods = [item for item in user_data['items'] if '魚竿' in item]
    if not rods:
        await interaction.response.send_message("❌ 你沒有任何魚竿可以切換！", ephemeral=True)
        return

    # 建立一個選項清單供使用者選擇
    select_options = []
    for rod_name in rods:
        is_current = " (使用中)" if rod_name == user_data['current_rod'] else ""
        select_options.append(
            discord.SelectOption(label=f"{rod_name}{is_current}", value=rod_name,
                                 description=game_data['items'].get(rod_name, {}).get('description', ''))
        )

    # 如果選項太多，Discord Select 限制為 25 個
    if len(select_options) > 25:
        await interaction.response.send_message("你的魚竿太多了，無法一次性顯示所有選項。請聯繫管理員。", ephemeral=True)
        return

    select = discord.ui.Select(
        placeholder="選擇你的魚竿...",
        options=select_options,
        custom_id="rod_select_menu"
    )

    class RodSelectView(discord.ui.View):
        def __init__(self, user_id):
            super().__init__()
            self.user_id = user_id

        @discord.ui.select(
            placeholder="選擇你的魚竿...",
            options=select_options, # 使用外部定義的選項
            custom_id="rod_select_menu"
        )
        async def select_callback(self, interaction: discord.Interaction, select: discord.ui.Select):
            user_data = get_user_data(self.user_id)
            selected_rod = select.values[0]

            if selected_rod in user_data['items'] and '魚竿' in selected_rod:
                user_data['current_rod'] = selected_rod
                save_game_data() # 切換後保存
                await interaction.response.send_message(f"✅ 已切換到 **{selected_rod}**！", ephemeral=False)
            else:
                await interaction.response.send_message("❌ 無效的選擇或你沒有這個魚竿！", ephemeral=True)

    view = RodSelectView(interaction.user.id)
    await interaction.response.send_message("請選擇你要使用的魚竿：", view=view, ephemeral=True)

@bot.tree.command(name='shop', description='查看商店裡可用的釣魚用品。')
async def shop_command(interaction: discord.Interaction):
    """商店"""
    embed = discord.Embed(title="🏪 釣魚用品商店", color=0x00ff00)

    for item, info in game_data['items'].items():
        if item == '基本魚竿': # 基本魚竿通常不販售
            continue
        embed.add_field(
            name=f"{item}",
            value=f"價格: 💰{info['price']}\n描述: {info.get('description', '無')}",
            inline=True
        )

    embed.set_footer(text="使用 /buy <物品名稱> 來購買道具。")
    await interaction.response.send_message(embed=embed, ephemeral=True)

@bot.tree.command(name='buy', description='從商店購買物品。')
@app_commands.describe(item_name='要購買的物品名稱 (例如：高級魚竿)')
async def buy_command(interaction: discord.Interaction, item_name: str):
    """購買道具"""
    user_id = str(interaction.user.id)
    user_data = get_user_data(user_id)

    # 查找商品 (忽略大小寫和空格)
    normalized_input_name = item_name.lower().replace(' ', '')
    found_item_key = None
    item_info = None

    for key, info in game_data['items'].items():
        if key.lower().replace(' ', '') == normalized_input_name:
            found_item_key = key
            item_info = info
            break

    if not found_item_key or found_item_key == '基本魚竿': # 不能購買基本魚竿
        await interaction.response.send_message(f"❌ 商店中沒有 **{item_name}** 這個物品。", ephemeral=True)
        return

    price = item_info['price']

    if user_data['money'] >= price:
        user_data['money'] -= price
        if found_item_key not in user_data['items']:
            user_data['items'][found_item_key] = 0
        user_data['items'][found_item_key] += 1
        save_game_data() # 購買後保存

        await interaction.response.send_message(
            f"✅ 成功購買了 **{found_item_key}**！你現在有 💰{user_data['money']} 金錢。",
            ephemeral=False
        )
    else:
        await interaction.response.send_message(
            f"❌ 你的金錢不足！購買 **{found_item_key}** 需要 💰{price}，你只有 💰{user_data['money']}。",
            ephemeral=True
        )

@bot.tree.command(name='bag', description='查看你的背包、金錢和釣到的魚。')
async def bag_command(interaction: discord.Interaction):
    """查看背包"""
    user_id = str(interaction.user.id)
    user_data = get_user_data(user_id)

    embed = discord.Embed(title=f"🎒 {interaction.user.display_name} 的背包", color=0x9932cc)
    embed.add_field(name="💰 金錢", value=str(user_data['money']), inline=True)
    embed.add_field(name="🎣 當前魚竿", value=user_data['current_rod'], inline=True)
    embed.add_field(name="📊 總釣魚次數", value=str(user_data['total_catches']), inline=True)

    # 道具列表
    items_text = ""
    if user_data['items']:
        for item, count in user_data['items'].items():
            items_text += f"{item}: {count}\n"
    else:
        items_text = "無"
    embed.add_field(name="🛠️ 道具", value=items_text, inline=False)

    # 釣到的魚
    if user_data['fish_caught']:
        fish_text = ""
        # 按稀有度分類顯示 (可選)
        sorted_fish = sorted(user_data['fish_caught'].items(), key=lambda item: item[0]) # 簡單按名稱排序
        for fish, count in sorted_fish:
            # 嘗試獲取魚的稀有度，以便顯示對應表情
            fish_rarity = 'common' # 預設
            fish_emoji = '🐟' # 預設
            for rarity_type, fish_map in game_data['fish_data'].items():
                if fish in fish_map:
                    fish_rarity = rarity_type
                    fish_emoji = fish_map[fish]['emoji']
                    break
            rarity_emojis = {
                'common': '🟢', 'rare': '🔵', 'epic': '🟣', 'legendary': '🟡', 'junk': '⚫'
            }
            fish_text += f"{rarity_emojis.get(fish_rarity, '❓')} {fish}: {count} 條 {fish_emoji}\n"
        embed.add_field(name="🐟 釣到的魚", value=fish_text, inline=False)
    else:
        embed.add_field(name="🐟 釣到的魚", value="你還沒有釣到任何魚。", inline=False)

    await interaction.response.send_message(embed=embed, ephemeral=True)

@bot.tree.command(name='save', description='將你的遊戲進度保存為 JSON 檔案，以便下載。')
async def save_command(interaction: discord.Interaction):
    """保存玩家資料為檔案"""
    user_id = str(interaction.user.id)
    player_data = get_user_data(user_id)

    # 僅保存當前用戶的數據
    data_to_save_for_user = {user_id: player_data}
    json_string = json.dumps(data_to_save_for_user, indent=4, ensure_ascii=False)

    file_bytes = io.BytesIO(json_string.encode('utf-8'))

    filename = f'fishing_data_{user_id}.json'
    discord_file = discord.File(file_bytes, filename=filename)

    await interaction.response.send_message(
        f'{interaction.user.mention} 這是你的遊戲進度檔案。請妥善保存！\n'
        '下次遊玩時，可以使用 `/load` 指令上傳此檔案以繼續進度。',
        file=discord_file,
        ephemeral=True
    )

@bot.tree.command(name='load', description='上傳你的遊戲進度 JSON 檔案，繼續之前的進度。')
@app_commands.describe(file='請上傳你的 JSON 進度檔案')
async def load_command(interaction: discord.Interaction, file: discord.Attachment):
    """載入玩家資料檔案"""
    user_id = str(interaction.user.id)

    if not file.filename.lower().endswith('.json'):
        await interaction.response.send_message("❌ 請上傳一個 .json 檔案。", ephemeral=True)
        return

    try:
        file_content = await file.read()
        json_data = json.loads(file_content.decode('utf-8'))

        # 驗證檔案格式是否包含用戶ID
        if not isinstance(json_data, dict) or user_id not in json_data:
            await interaction.response.send_message(
                "❌ 檔案格式不正確或不是你的數據檔案。請確保檔案是包含你用戶ID的JSON。",
                ephemeral=True
            )
            return

        player_loaded_data = json_data[user_id]

        # 驗證必要數據欄位
        if not isinstance(player_loaded_data, dict) or \
           "money" not in player_loaded_data or \
           "items" not in player_loaded_data or \
           "current_rod" not in player_loaded_data or \
           "fish_caught" not in player_loaded_data or \
           "total_catches" not in player_loaded_data:
            await interaction.response.send_message(
                "❌ 檔案內容缺少必要的遊戲數據（金錢、道具、魚竿、魚獲等）。",
                ephemeral=True
            )
            return

        # 載入數據到當前遊戲狀態
        game_data['users'][user_id] = player_loaded_data
        save_game_data() # 載入後自動保存一次所有資料

        coins = game_data['users'][user_id]["money"]
        items_str = ", ".join([f"{item} x{count}" for item, count in game_data['users'][user_id]["items"].items()]) if game_data['users'][user_id]["items"] else "無"

        await interaction.response.send_message(
            f'✅ {interaction.user.mention} 你的遊戲進度已成功載入！\n'
            f'你現在有 **💰{coins}** 金錢，背包物品：{items_str}。',
            ephemeral=False
        )

    except json.JSONDecodeError:
        await interaction.response.send_message("❌ 無效的 JSON 檔案內容。", ephemeral=True)
    except Exception as e:
        print(f"載入檔案時發生錯誤: {e}")
        await interaction.response.send_message(f"❌ 載入檔案時發生錯誤：{e}", ephemeral=True)

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
def get_all_data():
    """顯示所有遊戲資料 (僅供檢查)"""
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
        try:
            bot.run(BOT_TOKEN)
        except discord.errors.LoginFailure:
            print("❌ 無效的機器人 Token，請檢查 DISCORD_BOT_TOKEN 環境變數。")
        except Exception as e:
            print(f"機器人啟動時發生錯誤: {e}")
    else:
        print("❌ 請設定 DISCORD_BOT_TOKEN 環境變數。")
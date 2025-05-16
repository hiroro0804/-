import discord
from discord.ext import commands
import re
from collections import defaultdict
from datetime import datetime, timezone, timedelta
import jaconv
import json
import csv
import os

# Discordの権限設定
intents = discord.Intents.default()
intents.message_content = True  # メッセージ本文の取得を許可
intents.reactions = True        # リアクション取得を許可
intents.members = True          # メンバー情報取得を許可

# Botのプレフィックス設定
bot = commands.Bot(command_prefix="!", intents=intents)

# 日本時間（JST）設定
JST = timezone(timedelta(hours=9))

# 犯罪名とその別名（ひらがなに変換して一致させる）
CRIME_ALIASES = {
    "コンビニ強盗": ["コンビニ"],
    "フリーカ強盗": ["フリーカ"],
    "モーテル強盗": ["モーテル"],
}

# 各犯罪ごとの成功時報酬（円）
CRIME_PAYMENT = {
    "コンビニ強盗": 200000,
    "フリーカ強盗": 200000,
    "モーテル強盗": 500000,
}
# 失敗時の報酬
FAIL_PAYMENT = 100000

# 犯罪名をメッセージから推測（部分一致、ひらがな化）
def match_crime_name(text):
    hira_text = jaconv.kata2hira(text)
    for canonical, aliases in CRIME_ALIASES.items():
        for alias in aliases:
            alias_hira = jaconv.kata2hira(alias)
            if alias_hira in hira_text:
                return canonical
    return None

# 報酬データをファイルに保存（JSON + CSV）
def save_data(participant_rewards):
    with open("data.json", "w", encoding="utf-8") as f:
        json.dump(participant_rewards, f, ensure_ascii=False, indent=2)
    with open("data.csv", "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["名前", "報酬（円）"])
        for name, reward in participant_rewards.items():
            writer.writerow([name, reward])

# メインコマンド: !calculate [開始日] [終了日]
@bot.command()
async def calculate(ctx, start_date: str = None, end_date: str = None):
    try:
        if start_date and end_date:
            # 日本時間で日付を解析
            start_time = datetime.strptime(start_date, "%Y/%m/%d").replace(tzinfo=JST)
            end_time = datetime.strptime(end_date, "%Y/%m/%d").replace(hour=23, minute=59, tzinfo=JST)
        else:
            # デフォルトは直近7日間
            end_time = datetime.now(JST)
            start_time = end_time - timedelta(days=7)
    except ValueError:
        await ctx.send("日付の形式が正しくありません。例: `!calculate 2025/05/08 2025/05/11`")
        return

    source_channel_id = 1342103011396288512  # 収集対象のチャンネルID
    source_channel = bot.get_channel(source_channel_id)
    output_channel = ctx.channel  # 出力先はコマンドが送られたチャンネル

    if not source_channel or not output_channel:
        await ctx.send("指定チャンネルが見つかりません。")
        return

    # 報酬、勝率統計の格納用辞書
    participant_rewards = defaultdict(int)
    participant_total = defaultdict(int)
    participant_rich = defaultdict(int)
    unpaid_participants = defaultdict(int)

    # Discordのメッセージ検索はUTC時刻
    utc_start_time = start_time.astimezone(timezone.utc)
    messages = [m async for m in source_channel.history(limit=200, after=utc_start_time)]

    for message in messages:
        text = message.content
        crime_match = re.search(r"犯罪種類\[(.*?)\]", text)
        if not crime_match:
            continue

        # 犯罪名を取得・正規化
        crime_raw = crime_match.group(1)
        crime = match_crime_name(crime_raw)
        if not crime:
            continue

        has_win_reaction = False
        has_lose_reaction = False
        reward_receivers = set()

        # リアクションをチェック
        for reaction in message.reactions:
            emoji_str = str(reaction.emoji)
            if emoji_str == '⭕️':
                has_win_reaction = True
            elif emoji_str == '❌':
                has_lose_reaction = True
            elif emoji_str == '✅':
                # ✅ リアクションをつけた人を報酬対象にする
                async for user in reaction.users():
                    if not user.bot:
                        reward_receivers.add(user.display_name)

        # 勝率集計（⭕️か❌の片方だけある場合）
        if (has_win_reaction or has_lose_reaction) and not (has_win_reaction and has_lose_reaction):
            participant_total[crime] += 1
            if has_win_reaction:
                participant_rich[crime] += 1

        # ✅リアクションをつけた人にのみ報酬を与える
        for name in reward_receivers:
            if has_win_reaction and not has_lose_reaction:
                participant_rewards[name] += CRIME_PAYMENT.get(crime, 500000)
            else:
                participant_rewards[name] += FAIL_PAYMENT
            unpaid_participants[name] += 1

    # 結果出力
    await output_channel.send(f"=== 危険手当未受け取りのメンバー ===\n{start_time.strftime('%Y/%m/%d %H:%M')} ～ {end_time.strftime('%Y/%m/%d %H:%M')}")
    for name, reward in participant_rewards.items():
        await output_channel.send(f"・{name} : {reward}円")

    total_reward = sum(participant_rewards.values())
    await output_channel.send(f"\n=== 合計支給額: {total_reward}円 ===")

    await output_channel.send("\n=== 犯罪別勝率統計 ===")
    for crime in sorted(participant_total.keys()):
        total = participant_total[crime]
        rich_count = participant_rich[crime]
        rate = round((rich_count / total) * 100) if total else 0
        await output_channel.send(f"{crime}: {rate}% ({total}件中 {rich_count}件が金持ち検挙)")

    # データ保存
    save_data(dict(participant_rewards))

# Bot起動
bot.run(os.getenv("DISCORD_TOKEN"))

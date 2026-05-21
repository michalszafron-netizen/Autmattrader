Chapter 1: Intro
0:00Right now, while you're watching this, an invisible war is happening inside the order books of every major exchange.
0:066 secondsMillions of decisions are being made in milliseconds.
0:1010 secondsPositions are being hedged, stops are being hunted, and whales are moving sides without leaving a footprint.
0:1717 secondsMost people think they're trading against other people. They aren't. You are trading against silicon. You are trading against algorithms that don't
0:2424 secondssleep, don't feel fear, and don't make mistakes. In this course, we aren't just going to learn about these systems. We are going to build one. We are going to
0:3131 secondsmove through the complete stack. First is the brain. We're going to be wiring Claude to open router for institutionalgrade model access. Second,
0:4040 secondsthe eyes. We will be installing the hyperlquid whale tracker to see smart money in real time and the trading view MCP to let Claude read your charts
0:4848 secondsdirectly. Third, the hands where we will be connecting weeks, alpaca, and interactive brokers for multimarket execution. Fourth, the workforce where
0:5757 secondswe will be deploying agent frameworks like Senpai, Hermes, and OpenClaw specialists that hunt for alpha while you sleep. Fifth is the command center
1:061 minute, 6 secondswhere we will be shipping a custom Python bot to a 24/7 VPS and unifying everything into a live ops dashboard. By
1:131 minute, 13 secondsthe time we're done, you won't be staring at 12 browser tabs and second-guessing your entries. You'll be an operator. You'll wake up to a daily alpha brief waiting in your inbox, a bot
1:221 minute, 22 secondsmanaging your risk, and a system that finally puts you on the right side of the silicon war. Let's get into it. AI
Chapter 2: MODULE 0: Surviving the Silicon War
1:301 minute, 30 secondsis already a big part of trading cryptocurrency. Not in theory, not in some lab somewhere. Live, onchain, and
1:371 minute, 37 secondsverifiable. There's a bot on Poly Market with a wallet address named Sovereign 2013 that turned $1 into $3.3 million using
1:471 minute, 47 secondsAI. That's not a headline I made up. You can look it up on chain right now. This course is built on the blueprint established by pioneers like Jake Nesler
1:551 minute, 55 secondswho let Claude Code run a live trading stack with $100,000 of real capital.
2:002 minutesEvery prompt, every draw down, and every winning trade was documented. It proved a vital point. When you give an agent the wheel, it doesn't just help you
2:082 minutes, 8 secondstrade, it is the trader. We are generalizing that exact stack here. Add in three specific skills, five agent
2:162 minutes, 16 secondsframeworks, and clawed routines to create a system that doesn't just survive the market, but masters it. And on Hyperlid, an experiment called the
2:242 minutes, 24 secondsalpha arena took the biggest AI models in the world. Quen, Deepseek, Claude, GPT, Grock, and Gemini gave each of them
2:332 minutes, 33 seconds$10,000 and let them trade live perpetuals against each other. The results were not even close. Some of these models, models that millions of
2:422 minutes, 42 secondspeople are using right now to make trading decisions, lost the majority of their account in four days. And one of them did the complete opposite. AI
2:502 minutes, 50 secondspowered bots now account for roughly 70 to 80% of all crypto volume. If you are still trading manually, you are not
2:582 minutes, 58 secondscompeting with other retail traders anymore. You are the liquidity. You are the other side of the trade that the AI is taking. That is not me trying to
3:063 minutes, 6 secondsscare you. That is just what is happening right now. And here's the thing. The tools that are creating this gap are not locked behind a hedge fund.
3:153 minutes, 15 secondsThey are not expensive. They are not complicated. Claude costs $20 a month.
3:203 minutes, 20 secondsThe hyperlquid API is completely free and public. Trading View you probably already have. Telegram you already have
3:273 minutes, 27 secondson your phone. The gap is not about access. The gap is about knowing how to put it together. This is the complete zero to hero course for AI trading with
3:363 minutes, 36 secondsClaude. I'm not going to give you theory. I'm not going to show you a demo that looks impressive but falls apart the moment you try to replicate it.
3:443 minutes, 44 secondsEverything I show you today I have built and run myself. This is what you should expect. The exact contract for the next 2.5 hours. Real money, every tool.
3:543 minutes, 54 secondsClaude plus Openro which gives you the key for every model. Three skills live.
3:593 minutes, 59 secondsWix Trader, Whale Tracker, and Trading View MCP. Three brokers connected. Wix, Alpaca, and Interactive Brokers. Poly Market Plus, Calshi Prediction Markets.
4:104 minutes, 10 secondsClaude Routines automating your entire trading day. Agent PNL plus SEI plus Hermes plus OpenClaw. All deployed.
4:194 minutes, 19 secondsCustom Python bot on Hoster running 247.
4:224 minutes, 22 secondsTelegram bot in your pocket. Custom dashboard tracking it all. Nothing skipped. Every command on screen. If you already code, skim. If you don't, then we're going to open a terminal together.
4:324 minutes, 32 secondsLet's go. Before I show you anything, I need to say something that most AI trading videos will never tell you.
4:384 minutes, 38 secondsBecause if you come into this with the wrong expectation, you're going to get hurt. Here is what AI is genuinely good at. Writing code, building back test
4:474 minutes, 47 secondsscaffolding, synthesizing news from 10 different sources into one clean summary. sentiment analysis, reading a chart screenshot and giving you a
4:554 minutes, 55 secondsstructured technical breakdown, journaling your trades and finding patterns in your own data, risk logic, and turning a plain English strategy
5:035 minutes, 3 secondsidea into working Pinescript in under a minute. All of that Claude does better than any human working alone. Faster,
5:105 minutes, 10 secondsmore consistently, and without getting tired at 2 in the morning. Here is what AI is bad at. Price prediction. Full
5:175 minutes, 17 secondsstop. Claude cannot tell you where Bitcoin is going tomorrow. Nobody can.
5:225 minutes, 22 secondsAnd any tool that claims it can is lying to you, replacing your judgment. The market will always throw situations that
5:295 minutes, 29 secondsno model has seen before. Black swan events, coordinated manipulation, macro shocks. AI has no edge in those moments.
5:375 minutes, 37 secondsYou do, and hallucinations. Claude will occasionally state something confidently that is completely wrong. A price that
5:445 minutes, 44 secondsdoes not exist, a ticker that is not real, a statistic it invented. It does not happen constantly, but it happens.
5:525 minutes, 52 secondsYou always verify the critical data points yourself. So, here's the one rule I want you to carry through this entire course. Claude is a research assistant
6:006 minuteswith execution hands, not an oracle. It does the work faster than you can. It catches things you would miss. It runs
6:076 minutes, 7 secondswhile you sleep, but it does not replace your judgment. It extends it. Keep that in your head, and everything I show you today will make sense. Forget it and you
6:166 minutes, 16 secondswill eventually hand an AI your account and wonder what happened. This course makes you capable of executing faster, not capable of predicting markets. Trade
6:266 minutes, 26 secondssmall until your own P&L proves otherwise. Now, before we get a deep dive into the course, here's what you need on your desk before you start.
6:346 minutes, 34 secondsFirst, a laptop or a computer, Mac, Windows 11, or any modern Linux distro with at least 8 GB RAM minimum, but a 16
6:436 minutes, 43 secondsGB is recommended. Any CPU from the last 5 years is fine. Second is any reasonable internet connection. You're not streaming, you're making API calls.
6:526 minutes, 52 secondsA cafe hotspot works. Third is at least 2.5 hours of your time. You can do it in chunks, but the install spine that
6:596 minutes, 59 secondscovers from modules 3 to 11 will benefit you from one continuous block. Fourth, a credit card for a few optional charges.
7:077 minutes, 7 secondsSome tools needs to be paid like $5 for open router credit, $5 for firecrawl, hosting durps which is around $5 to $8
7:157 minutes, 15 secondsper month, railway for senpi which is $5 per month after 30-day trial. Everything else is free tier. Before we dive into
7:237 minutes, 23 secondsthe modules, let's get your digital workspace organized. You'll want these apps open, signed in, and ready on your desktop. First, terminal. Any modern
7:337 minutes, 33 secondsterminal will do. IT term for Mac, Windows terminal, PowerShell or your default Linux terminal. You'll be pasting commands here starting from
7:417 minutes, 41 secondsmodule 3. Second, browser. You'll use this to sign into claude, open router, polyarket, and other essential
7:497 minutes, 49 secondsplatforms. Third, cursor. You'll need this code editor to view and edit markdown.md files, python. py files, and dashboard html as the course progresses.
8:018 minutes, 1 secondFourth, phone. Keep your phone handy for Telegram. You'll need it for the integration steps once we start working with BotFather. Now, for the first module, we will talk about Foundation.
Chapter 3: MODULE 1: Foundation
8:128 minutes, 12 secondsBefore we open the terminal, we need to align on the mental model. Most retail traders fail with AI because they only use it for one thing, asking for a strategy. That's 5% of the capability.
8:238 minutes, 23 secondsTo win, we install AI into all three layers of the trading system. First is research. This is finding the edge.
8:318 minutes, 31 secondsWe're talking about tracking hyperlquid whales, using firecrawl to scrape the open web for sentiment and generating a daily alpha brief that compresses
8:408 minutes, 40 secondsthousands of data points into the three things that actually matter. Second is strategy. This is turning that edge into
8:468 minutes, 46 secondsrules. We use the trading view mcp which gives claude 78 specific tools to autob build pine script run back tests and look for multi-time frame confluence.
8:578 minutes, 57 secondsThird is execution. This is moving capital. We use the Wix trading assistant skill to execute orders, use Trading View to send commands via web
9:059 minutes, 5 secondshook, set agentic risk management, and deploy custom bots on Hostinger that stay online 247. The edge isn't just one
9:139 minutes, 13 secondsof these. It's the connection between them. Now, AI isn't magic. It's a force multiplier. It gives you four specific advantages that any retail trader can
9:229 minutes, 22 secondsnow rent for pennies. Reading speed. It reads a 100 filings while you read one.
9:279 minutes, 27 secondsYou can give a model 300 documents and it will return the outliers in 30 seconds for about 25 cents. Production code, it writes professional-grade
9:359 minutes, 35 secondsPython. We're talking CCXT rappers and SQL light journals that pass every check and run live on the first try. Pattern
9:439 minutes, 43 secondsrecognition, our whale tracker can scan 33,000 wallets in 90 seconds. It sorts every profitable trader by P&L and
9:529 minutes, 52 secondssentiment while you're still refreshing a tab. Uptime, you sleep. the bot doesn't. Your system services and clawed
9:599 minutes, 59 secondsroutines run forever. This is an autonomous stack that earns while you're offline. Now, before we get into the tools, let me quickly demystify terms
10:0810 minutes, 8 secondsyou're going to hear constantly in this space. Because if you do not know what these mean, some of this is going to feel more complicated than it actually
10:1510 minutes, 15 secondsis. Let's define them now so we don't slow down later. MCP, the model context protocol. Think of it like a USBC port
10:2410 minutes, 24 secondsfor Claude. It lets us plug in any broker, chart, or data source. Open router. This is our unified gateway. One API key that gives us access to Claude,
10:3310 minutes, 33 secondsGPT, Gemini, and DeepSeek with automatic fallback. Claude has what Anthropic calls skills. Think of them like apps
10:4010 minutes, 40 secondsyou install on your phone. Someone builds a skill for hyperlquid whale tracking. You install it. Now, Claude can do that automatically without you
10:4810 minutes, 48 secondswriting a single line of code. I'm going to show you how to use these later in the course. API which means application programming interface. This is the
10:5610 minutes, 56 secondsmachine readable door that connects claw directly to weeks, alpaca, interactive brokers, trading view, everything. VPS,
11:0411 minutes, 4 secondsyour virtual private server, a Linux box we rent for a few dollars a month. So your bot lives in the cloud, not just on your laptop. Routines. Anthropics cloud
11:1411 minutes, 14 secondshosted tasks. You schedule a prompt and it runs on their infrastructure even when your laptop is closed. agents
11:2111 minutes, 21 secondssoftware that loops. It plans, acts, observes, and replans. We'll be deploying five different frameworks, including Senpai, Hermes, and OpenClaw.
11:3111 minutes, 31 secondsPrediction markets, places like Poly Market and Khi. LLMs are shockingly good here because they compress massive
11:3811 minutes, 38 secondsamounts of context to predict real world outcomes. The skills thesis and why this course leans heavily on Claude skills.
11:4511 minutes, 45 secondsMost people think prompt engineering is the secret. It's not. A skill is a folder. Inside is a specialized file that teaches Claude a whole domain.
11:5411 minutes, 54 secondsEvery command, every edge case, and every safe default. By dropping three specific skills into the system, Claude
12:0212 minutes, 2 secondssuddenly knows how to trade Wix per track Hyperlquid whales and control your Trading View desktop with 78 built-in
12:0912 minutes, 9 secondstools. No manual coding required, no prompt engineering, just plugandplay capability. These are the Lego bricks.
12:1512 minutes, 15 secondsNow, let's go build the stack. Now, the second module covers the complete AI trading stack. This is the one-page map.
Chapter 4: MODULE 2: The Complete AI Trading Stack
12:2212 minutes, 22 secondsEvery tool, every broker, every agent platform, and every skill. If some name sounds unfamiliar right now, don't
12:2912 minutes, 29 secondsworry. Every single box on this map gets its own dedicated installation module later. Right now, I want you to see how
12:3612 minutes, 36 secondsthe Lego blocks fit together. One models plus open router. Everything starts with a key. We use open router because it
12:4412 minutes, 44 secondsgives us one single API key to access over 300 models. No vendor lockin. If anthropic goes down, we fall back to
12:5212 minutes, 52 secondsDeepSeek or Quinn in 1 second. Now, Claude has three different models, all with different strengths for different output. First is Claude Opus 4.7. This
13:0113 minutes, 1 secondis the flagship of anthropic made for heavy strategy design, code review, and polyarket analyzer reasoning. Second is
13:0813 minutes, 8 secondsClaude 4.6 Sonnet. This model will be our workhorse. 90% of this course runs on it. Third is Claude Haiku 4.5. This
13:1613 minutes, 16 secondsis for the cheap labor. This is mostly used for classifying news, triaging routines, and classification of takes
13:2313 minutes, 23 secondsfor pennies. Other models include GPT, Gemini, and Deepseek. You can swap these into your configuration at any time
13:3113 minutes, 31 secondswithout changing your routines. This is incredibly useful for skeptic panel reviews where you have multiple models
13:3913 minutes, 39 secondscritique a trade idea before you pull the trigger. Next is Quinn and Kimmy. These are your long context open models.
13:4513 minutes, 45 secondsIf you need to ingest a 100page 10K filing or summarize massive log files on a budget, these are your go-to tools.
13:5313 minutes, 53 secondsAlso, with Open Router, you can even set your model to auto. This tells the system to automatically choose the cheapest, most capable model available for the specific task you're running.
14:0414 minutes, 4 secondsIt's the ultimate way to optimize your overhead while keeping your Hermes and OpenClaw agents running 24/7. All right,
14:1114 minutes, 11 secondsbefore we touch a single terminal, you need to understand what Claude actually is. There are three versions you need to know about. The first is claude.ai.
14:2014 minutes, 20 secondsThis is the browser version. Think of it as the research assistant. You paste in a chart screenshot, a news article, a
14:2714 minutes, 27 secondstoken contract. It reads it and gives you a structured breakdown. No code, no setup. Just open a tab and go. The second is clawed desktop with co-work.
14:3814 minutes, 38 secondsThis is where it gets agentic. Co-work does not just talk, it acts. It can open apps on your computer, read and edit
14:4614 minutes, 46 secondsfiles, run scheduled tasks, and remember context across sessions. So it knows what you told it yesterday. It knows
14:5414 minutes, 54 secondsyour trading setup. It works in the background while you are doing something else. The third is Claude code. This is the most powerful version. It is a
15:0315 minutes, 3 secondscommand line tool that writes, runs, and iterates code autonomously. This is what built the trading bots I'm going to show
15:1015 minutes, 10 secondsyou later. This is what connects to your exchange and executes real trades. Now, let's talk about where the money actually moves. We connect to three
15:1815 minutes, 18 secondsprimary brokers plus prediction markets plus the CCXT library for everything else. First is Wix. This is our primary
15:2715 minutes, 27 secondscrypto broker. It's no KYC, offers a massive deposit bonus, and most importantly, it has a V3 API built
15:3415 minutes, 34 secondsspecifically for AI integration. It handles futures and spot in one account.
15:3915 minutes, 39 secondsSecond is Alpaca. This is your home for US stocks and options. It's commission free and has the best Python SDK in the
15:4615 minutes, 46 secondsgame. It even has an official MCP server for claw desktop. Third is interactive brokers. This is for the pros. If you're
15:5415 minutes, 54 secondstrading global markets, bonds or CFDs, this is the requirement. We use the IBN sync Python library for prograde
16:0216 minutes, 2 secondsexecution. We're also hitting prediction markets, which is where that $3 million bot lives I mentioned earlier. The first
16:0916 minutes, 9 secondsone is Poly Market. This is the global giant for cryptofunded event betting koshi which is the US regulated
16:1616 minutes, 16 secondsalternative for polyarket PMXT. This is a unified SDK that lets us arbitrage between Poly Market and Kshi. If the
16:2516 minutes, 25 secondssame event has different prices on Poly Market and Khi, the AI locks in the profit automatically. And for everything else, we have CCXT.
16:3616 minutes, 36 secondsThis is the universal translator for over 100 exchanges. It's how we talk to Binance for back testing and blowfin as
16:4316 minutes, 43 secondsa low latency backup in a great week's alternative. Finally, there's hyperlquid. It has a free public API that requires no key for data reads.
16:5316 minutes, 53 secondsThis is where our whale tracker skill pulls live data to see what the biggest fish in the pond are doing. With this course, you aren't just getting one bot.
17:0117 minutes, 1 secondYou're getting five different frameworks where each does one thing better than the others. Most power users run a combination of these to cover every
17:0917 minutes, 9 secondscorner of the market. First is Asian P&L. This is the easiest entry point.
17:1417 minutes, 14 secondsIt's a plain English weeks perpetuals agent. You can go from copy paste to live trading in under two minutes. It
17:2117 minutes, 21 secondseven has a public leaderboard so you can see how your logic stacks up. Second is sentby. This is your personal trading
17:2817 minutes, 28 secondspowerhouse for hyperlid. It comes with 44 specialized MCP tools and is battle tested with over $100 million in volume.
17:3717 minutes, 37 secondsUnder the hood, it's powered by OpenClaw. Third is Hermes. Developed by Noose Research, this Pythonbased
17:4417 minutes, 44 secondsframework is a beast with 95,000 stars on GitHub. It's self-improving, meaning it generates reusable skills from every
17:5217 minutes, 52 secondssuccessful task. It's also your gateway to Telegram, Discord, and Slack. Fourth is OpenClaw. This is the heavyweight of
17:5917 minutes, 59 secondsthe ecosystem with 345,000 stars. Built on Typescript and Node.js,
18:0618 minutes, 6 secondsit has the broadest integration possible. Over 50 channels and 13,000 community skills via Clawhub. Fifth is
18:1418 minutes, 14 secondsClaude routines. These are anthropics cloud hosted scheduled tasks. This is how your logic stays alive and running
18:2118 minutes, 21 secondseven when your laptop is closed. You don't have to choose just one. We're going to install all five and you'll pick the combination that fits your
18:2818 minutes, 28 secondsspecific trading style. Finally, we drop three super skills directly into your Claude code. This is the unfair advantage of this course. Whale Tracker,
18:3718 minutes, 37 secondsrealtime hyperlquid whale research with zero API keys. Trading View MCP, 78 tools that let Claude literally control
18:4418 minutes, 44 secondsyour Trading View desktop. Scanning charts and writing Pine Script for you.
18:4818 minutes, 48 secondsWe trading assistant that lets you execute trades all in plain English. Individually, these tools are powerful.
18:5518 minutes, 55 secondsCombined, they create the daily alpha brief where your AI tracks the whales, reads the charts, checks your portfolio,
19:0219 minutes, 2 secondsand hands you the day setups on a silver platter. Study the map on this page. Bookmark the labels you don't know.
19:0919 minutes, 9 secondsLet's start plugging them in, which is exactly what we're going to do in the next module. In this module, we are installing every essential tool you'll
Chapter 5: MODULE 3: Workstation Setup
19:1719 minutes, 17 secondsneed throughout the course. Five installs, five verify commands, and one project folder. This is the foundation.
19:2419 minutes, 24 secondsEvery module that follows assumes this setup is perfectly in place. If you skip a step here, the bots won't run, the API won't connect, and you'll be
19:3219 minutes, 32 secondstroubleshooting code instead of trading markets. We're going to open five tabs and install these in order. Let's get to
19:3819 minutes, 38 secondswork. First is Python 3.12 or higher. Go to python.org. Click on on download Python. Once the installer is
19:4619 minutes, 46 secondsdownloaded, a pop-up will appear. Click on install Python and click yes to accept the terms. If you're on Windows, this is the most important part. Tick
19:5519 minutes, 55 secondsthe box that says add Python to path during the install. If you miss that, nothing else works. If you're on Mac and have homebrew, you can type the install command from the notes below instead.
20:0620 minutes, 6 secondsSecond is Node.js. Get the LTS version from node.js.org.
20:1220 minutes, 12 secondsThis is the engine for ARMCP servers and the open claw framework we'll deploy later. Choose your operating system.
20:1920 minutes, 19 secondsSince I'm using Windows, I'll select the Windows installer. Accept the license agreement, then click next until the installation is complete. Third is Git.
20:2720 minutes, 27 secondsDownload it from git-scm.com.
20:3120 minutes, 31 secondsWe'll be using this to clone or copy the trading skills and bot repositories directly to your machine. Just accept the default settings during the install.
20:4020 minutes, 40 secondsFourth is Cursor. This is our command center. Go to cursor.com. It's an AI native editor that allows Claude to actually see your code files. Click on download in the upper right corner.
20:5020 minutes, 50 secondsAccept the agreement, then click next until it installs. Fifth is your terminal. If you're on Mac, use the built-in terminal or iTerm 2. On
20:5920 minutes, 59 secondsWindows, use Windows Terminal from the Microsoft Store and always select the PowerShell tab. Never use the old cmd.x.
21:0721 minutes, 7 secondsOnce you can open PowerShell, you're done. Now, let's create your trading AI folder. This keeps the course clean and ensures Claude knows exactly where to
21:1521 minutes, 15 secondslook. Open your terminal and type the command on the screen. Everything we build from this point forward, every skill, every config file goes inside
21:2421 minutes, 24 secondsthis folder. Before we move to module 4, we need three green lights. Type these into your terminal one by one. pi- version. This must be 3.12 or higher.
21:3521 minutes, 35 secondsNode- version, you're looking for v22 or higher. Git- version. Anything in the
21:4221 minutes, 42 seconds2.4 range is perfect. If you get a command not found error for Python on Windows, it's because you didn't tick that add to path box. Don't fight it.
21:5221 minutes, 52 secondsJust rerun the installer. If note isn't showing up, close your terminal completely and reopen it to refresh the system. If you see those version
22:0022 minutesnumbers, you are officially ready. Your computer is no longer just a laptop.
22:0422 minutes, 4 secondsIt's a highfrequency workstation. Take a breath. Close your browser tabs. In the next module, we are installing Claude code and wiring up your open router
22:1322 minutes, 13 secondsmaster key. Let's get into it. In this module, we are installing Claude desktop, the Claude Code CLI, and
Chapter 6: MODULE 4: Claude + OpenRouter
22:2022 minutes, 20 secondssigning up for Open Router. By the end of this module, you will have one master key that points Claude at over 300
22:2722 minutes, 27 secondsdifferent AI models with Sonnet 4.6 as your default workhorse and Opus 4.7 for the heavy lifting. First, go to claw.ai.
22:3622 minutes, 36 secondsI highly recommend the pro plan for $20 a month. It unlocks Claude code and gives you the usage caps you need to actually trade. If you're planning on
22:4422 minutes, 44 secondsrunning whale alerts and risk checks 247, the Max plan is the move. Once you've picked a plan, download Claude desktop. Keep it pinned to your taskbar.
22:5322 minutes, 53 secondsLater in the course, we're going to plug our MCP servers directly into this app so Claude can see your charts and files.
23:0023 minutesNow, open that terminal we set up in from the last module. We are installing Claude Code. This is the command line interface where 70% of this course
23:0923 minutes, 9 secondshappens. Copy the install command from the notes below. If you see v2.x, you're live. Go ahead and type claw to run it
23:1623 minutes, 16 secondsfor the first time. It will give you a link to your browser. Just sign in with your pro account to authenticate. Next, open rotor.ai. Sign up. Then on the
23:2523 minutes, 25 secondsdashboard, click on get API keys and create a new key named trading AI course. Copy that string starting with
23:3223 minutes, 32 secondsSK or V1. Save it in a password manager immediately. Never paste this key into a public GitHub or chat room. This key is essentially a credit card for AI models.
23:4323 minutes, 43 secondsIf you leak it, bots will drain your credits in seconds. Go to credits and add a minimum of $5. At our scale, that will last you weeks of sonnet usage.
23:5223 minutes, 52 secondsNow, we have to tell claude code to use open rotor instead of talking to anthropic directly. This gives us the fallback protection if one provider goes down. We need to create a settings file.
24:0324 minutes, 3 secondsIn your terminal, you're going to create a folder called.clard and a file called settings.json.
24:0924 minutes, 9 secondsInside that file, you're going to paste the configuration block from the course notes. Replace the placeholder text with your actual open router key. This tells
24:1824 minutes, 18 secondsthe system, use open router is the base URL and use sonnet 4.6 as my primary
24:2524 minutes, 25 secondsmodel. Now, a quick alternative if you want to keep things simple. If you prefer to use direct anthropic billing and don't care about the multimodel
24:3324 minutes, 33 secondsfallback, you can skip open router entirely. It's a great fallback to keep in your back pocket and you can always switch between the two later as your
24:4124 minutes, 41 secondsstack grows. Let's verify the wiring. Go back to your terminal. Enter your trading folder and type claude. Once inside, ask it what model are you
24:4924 minutes, 49 secondsrunning on. Reply with the full model ID. If it says enthropic/clords 4.6 6 or Opus 4.7 and via Open Router.
24:5824 minutes, 58 secondsYou have successfully built an AI workstation that can think across any model on the planet. Finally, we're going to create a file called claude.md
25:0725 minutes, 7 secondsin your project route. This is Claude's persistent memory. Paste the house rules from the notes into this file. This
25:1425 minutes, 14 secondsensures that every time you open Claude, it remembers your brokers, your risk limits, and your goal. And this is how
25:2125 minutes, 21 secondsyou execute faster and trade smarter with Alex Carter. Now the brain is online. In the next module, we will start connecting it to the exchanges.
Chapter 7: MODULE 5: WEEX
25:3025 minutes, 30 secondsNow for this module, we will connect Claude to Weeks, which is our primary crypto broker. We're using Weeks because it is built for this specific type of AI
25:3925 minutes, 39 secondsautomation. It has a V3 API that's incredibly stable. It offers a $30,000 deposit bonus for new accounts, and it
25:4725 minutes, 47 secondsallows you to get live in about 90 seconds with no KYC required for initial trading. Full transparency, we partner
25:5525 minutes, 55 secondswith Weeks. We chose them because their API doesn't choke when an AI agent like Claude starts firing multiple requests
26:0226 minutes, 2 secondsper second. If for any reason Weeks doesn't work in your region, don't panic. This entire course is CCXT
26:1026 minutes, 10 secondscompatible, meaning you can swap Weeks for Binance or Kraken with a single line of code in which we will cover later on this course. First, use the VIP link in
26:1926 minutes, 19 secondsthe notes below to sign up. Use a strong unique password. Verify your email and make sure that VIP code is attached so you qualify for the trading credits.
26:2926 minutes, 29 secondsBefore you touch the API, you must enable two-factor authentication. Go to account, then security, and turn on Google Authenticator. Weeks will not
26:3726 minutes, 37 secondseven allow you to create API keys without this. Save your backup codes offline. If you lose your phone and your backup codes, you'd lose the account.
26:4626 minutes, 46 secondsPeriod. Now, fund your wallet. Click on deposit. I recommend using USDT via the Polygon or TRC20 networks. They have the
26:5426 minutes, 54 secondslowest fees. Once the funds land, transfer them from your spot wallet to your futures wallet. Our AI agents trade out of the futures wallet by default.
27:0327 minutes, 3 secondsNever fund more than you are comfortable losing. Remember, most retail derivatives accounts lose money. Start small. Now, let's create the machine's
27:1227 minutes, 12 secondscredentials. Go to API management and create a new key. Label it AI trading bot. You must tick these three boxes and
27:2027 minutes, 20 secondsonly these three. First is read so the AI can see your balance. Second is trade via spot or futures so the AI can execute orders. Third is IP whitelist.
27:3227 minutes, 32 secondsThis is non-negotiable. If you see a withdrawal box, never enable it. If your API key ever leaks and withdrawal is
27:3927 minutes, 39 secondsenabled, your funds are gone. By whitelisting your current IP address, you ensure that even if someone steals your key, it physically won't work from
27:4827 minutes, 48 secondsany other computer but yours. Weeks is going to give you three values: an API key, an API secret, and a passphrase.
27:5627 minutes, 56 secondsWeek shows that secret exactly once. If you close the window before saving it, you have to delete the key and start over. Copy all three and put them
28:0528 minutes, 5 secondsstraight into your password manager. Do not put them in a text file. Do not email them to yourself. You now have a funded account, two FAS live, and you
28:1428 minutes, 14 secondshave your three credentials tucked away in a secure spot. In module 8, we're going to drop these into Claude and let the agent take its first look at the
28:2128 minutes, 21 secondsmarkets. But first, we need to handle your equity in global markets, which we will cover in the next module. Now, in this module, we're moving into the heart
Chapter 8: MODULE 6: Alpaca
28:3028 minutes, 30 secondsof the US markets. We use Alpaca because it is quite simply the only broker that makes clawdriven trading trivial. Why
28:3828 minutes, 38 secondsAlpaca? First, commission-free API trading. Zero fees on US stocks and ETF. Second, the paper trading is instant.
28:4628 minutes, 46 secondsYou sign up and you get a $100,000 fake money account with zero KYC to start. Third, it supports fractional shares.
28:5428 minutes, 54 secondsYou can tell Claude by $50 of Apple and it handles the math for the decimal shares. But the killer feature is the
29:0129 minutes, 1 secondofficial MCP server. This drops straight into Claude desktop, giving Claude trading hands without you writing a
29:0829 minutes, 8 secondssingle line of Python. Go to alpaca.markets and sign up. Once you verify your email, head to your dashboard. Look for API keys and make
29:1829 minutes, 18 secondssure you select paper first. Generate your keys and copy both the key ID and the secret key immediately. Label these
29:2629 minutes, 26 secondsclearly in your password manager as alpaca paper. It is shockingly easy to accidentally fire a live order when you
29:3329 minutes, 33 secondsthink you're on paper. Don't be that guy. Now, we're going to give Claude Desktop its hands. We need to edit a file called claw desktop config.json.
29:4329 minutes, 43 secondsIn the course notes, find the alpaca mcp block. You're going to paste that into your config file, replacing the placeholders with your paper API keys.
29:5329 minutes, 53 secondsMake sure the line that says alpaca paper is set to true. Once you save that file, restart Claude desktop completely.
30:0130 minutes, 1 secondQuit the app, then reopen it. This is the moment. We're going to give Claude a plain English prompt. Cut. Use Alpaca to buy $200 of NVDA at market on the paper
30:1130 minutes, 11 secondsaccount. Show me my bounce first to confirm we're on paper, then place the order. Watch what happens on your screen. Claude will call the balance
30:1830 minutes, 18 secondstool. Verify the alpaca paper flag is true, then fire the order. If you have your Alpaca dashboard open in a browser
30:2630 minutes, 26 secondstab, you'll see that order appear in under a few seconds. From this, you can give Claude prompts for stocks plus ETF,
30:3330 minutes, 33 secondsfractional, options, and more. You now have a system where you can manage your entire portfolio with natural language.
30:4130 minutes, 41 secondsYou can ask for your daily P and L scan options chains for next Friday or add Meta and Microsoft to a new AI watch
30:4830 minutes, 48 secondslist. In module 12, we're going to take this a step further by combining this alpaca data with your week's crypto positions to create a unified daily
30:5730 minutes, 57 secondsalpha brief. Your stock market engine is officially online. Now, in this module is for the mode advanced traders. If you
Chapter 9: MODULE 7: Interactive Brokers
31:0431 minutes, 4 secondsplan on trading global markets, futures or forex at a professional scale, you will eventually land at interactive brokers. While retail apps are great for
31:1331 minutes, 13 secondsgetting started, IBKR is the endgame broker. It gives you one login to trade nearly every major exchange on the
31:2031 minutes, 20 secondsplanet from New York to Tokyo. A quick warning, IBKR is a serious institution.
31:2631 minutes, 26 secondsTheir KYC process takes about two to three business days for approval. If you're watching this right now, go sign up today. Everything else in this course still works while you wait for approval.
31:3731 minutes, 37 secondsAnd you can start on their paper trading account immediately. Go to interactivebrokers.com and open an account. Choose individual. The light
31:4631 minutes, 46 secondsversion is for casual investors. Pro is the one that gives us the API access we need. Once you're approved and funded, you're ready to connect the machines.
31:5531 minutes, 55 secondsUnlike Wix or Alpaca, IBKR API requires their desktop software to be open and logged in on your machine. You can use
32:0332 minutes, 3 secondsthe newer IBKR desktop or the classic trader workstation. For this course, I recommend TWWS. It is the battle tested
32:1132 minutes, 11 secondsgold standard for API. Once you're logged into TWWS, go to configuration, then API, and then settings. Check the
32:1932 minutes, 19 secondsbox that says enable active X and socket clients. Uncheck readonly API. We need clawed to have trading hands. Take note
32:2832 minutes, 28 secondsof your socket port. It should be 7497 for paper and 7496 for live. The official IBKR API is notoriously
32:3732 minutes, 37 secondsdifficult to code from scratch. That's why we use the IB insync library. It's the Python wrapper that every serious
32:4432 minutes, 44 secondsretail algo trader actually uses. Go to your terminal and run this. In the notes below, you'll find a 25line Python
32:5232 minutes, 52 secondsscript. This is the moment we bridge the gap. We're going to run a script that connects to your local TWWS session, identifies the Apple stock contract, and
33:0033 minutesfires a buy order for one share. Run the script, and in under two seconds, you'll see the order fill inside your TWWS
33:0733 minutes, 7 secondsdashboard. What's powerful here isn't just buying one share of Apple. It's that with three words of code, you can
33:1433 minutes, 14 secondsswitch from stocks to SNP500 futures or forex pairs. You're now trading at the same level as the hedge funds. Right
33:2233 minutes, 22 secondsnow, there isn't a native MCP for IBKR as stable as Alpacas. But we don't need one because we've installed the IB-NSYNC
33:3133 minutes, 31 secondslibrary. We can simply ask Claude code to write our scripts for us on demand.
33:3533 minutes, 35 secondsYou can ask Claude, "Write a Python script to check my open positions and close any that have a loss of more than 3%." Claude writes it, you run it, and
33:4433 minutes, 44 secondsthe job is done. One final rule for your claw.md file. Always tell Claude to default to port 7497.
33:5133 minutes, 51 secondsNever assume you are on a live port unless you explicitly say so. Your professional bridge is built. You now have the crypto engine, the stock market
33:5933 minutes, 59 secondsengine, and the global pro tier engine all ready to go. In this module, we are officially moving into the execution layer. Up until now, we've been building
Chapter 10: MODULE 8: WEEX Trading Asssistant
34:0834 minutes, 8 secondsthe machine. Now, we're giving it its first set of specialized skills. In this part of the course, we are installing the Wix trading assistant. This isn't
34:1734 minutes, 17 secondsjust a basic bot. This is a deep integration that allows Claude to open leverage futures, calculate position sizes based on risk math, and attach
34:2634 minutes, 26 secondsstop-loss and take profit orders, all from a single sentence in plain English.
34:3034 minutes, 30 secondsOpen your terminal. Navigate to your trading AI folder and launch Claude code. We're going to give Claude its first skill by pointing it to the
34:3834 minutes, 38 secondsrepository. Copy and paste the install prompt from the notes. You'll watch Claude perform a git clone to pull the skill into its specialized folder. Read
34:4734 minutes, 47 secondsthe documentation and summarize the tools it just learned. Once it's done, ask Claude. Check if the Y trader skill is installed and list its tools by
34:5534 minutes, 55 secondscategory. You should see a menu of tools covering everything from account balance to market data and futures execution.
35:0335 minutes, 3 secondsNow, we need to feed Claude the Wix credentials you saved in module 5. The safest way to do this is through your shell configuration. Tell Claude, "Help
35:1235 minutes, 12 secondsme open my shell config file so I can add environment variables for the weak skill." Claude will identify whether you need to edit your ZSRC on Mac or your
35:2135 minutes, 21 secondsprofile on Windows. You'll paste in your API key, secret, and passphrase. Once you save that file, reload your shell,
35:2835 minutes, 28 secondsand relaunch Claude. Your machine is now authenticated and ready to trade. Let's test the connection. Give Claude this prompt. Use the Wick skill to check my
35:3735 minutes, 37 secondsfutures balance. Show equity, available margin, and unrealized P&L. Claude will reach out to the Wick servers and return
35:4535 minutes, 45 secondsyour real-time account data. If you see an unauthorized error, double check your API secret and your IP whitelist from
35:5235 minutes, 52 secondsmodule 5. Now the moment you've been waiting for. We are going to execute a real riskmanaged trade with one prompt.
36:0236 minutes, 2 secondsCheck the current Bitcoin price. Then calculate a position size for a long where I risk exactly 2% of my portfolio
36:1036 minutes, 10 secondswith a 3% stop-loss and 10 times leverage. execute with SL and TP at 2.5 times my risk. Watch the terminal. Claw
36:1836 minutes, 18 secondsdoesn't just guess. It fetches the price, checks your actual equity, does the math to find the exact number of contracts, fires the order, and then
36:2736 minutes, 27 secondsattaches the stop-loss and take-profit orders immediately. Keep in mind, this is a real trade. If you just want to watch, tell Claw to do a dry run only.
36:3636 minutes, 36 secondsThe skill will show you the exact JS it would have sent without actually spending a dollar. The Wix trading assistant is now your 24/7 execution
36:4536 minutes, 45 secondsdesk. It handles futures with up to 125 times leverage. It handles spot buying and selling. It generates daily reports
36:5336 minutes, 53 secondsand journals your trades. It can even copy a setup from a screenshot. Tone finality. You just went from a retail
37:0137 minutes, 1 secondtrader to an AI augmented operator. I'll see you in module 9 where we install the whale tracker and start hunting for alpha. In this module, we will plug into
Chapter 11: MODULE 9: Hyperliquid Whale Tracker
37:0937 minutes, 9 secondswhat I call the most valuable free data set in all of crypto. Onchain whale activity on Hyperlid. Here's the beauty
37:1637 minutes, 16 secondsof this skill. No API keys, no signups, no monthly subscriptions. Just pure public data piped directly into Claude
37:2437 minutes, 24 secondsCode. We're giving your AI the ability to look at the smartest money in the world and ask, "What are they holding right now?" Hyperlid is a decentralized
37:3337 minutes, 33 secondsexchange where every single position is public. Entry prices, sizes, liquidations, it's all there. The whale
37:4037 minutes, 40 secondstracker skill wraps that data into functions Claude can understand. Instead of spending hours digging through block explorers, you just ask in plain English
37:4937 minutes, 49 secondswho is net long Bitcoin right now and get an answer in seconds. First, we need one lightweight Python package called request. This is what allows the skill
37:5837 minutes, 58 secondsto talk to the internet. Open your terminal and run this prompt. Now, let's install the skill. Go to this link and click download skill. Unzip the folder.
38:0838 minutes, 8 secondsWe need to move it into your.claude/skills directory. Copy the commands from the notes below. There's one for Mac and a specific PowerShell version for Windows.
38:1838 minutes, 18 secondsOnce that folder is moved, relaunch Claude code. You've just given your assistant a set of onchain eyes. Let's see it in action. This is the moment
38:2638 minutes, 26 secondsthat usually goes viral. Drop this prompt into Claude. What are the top 20 whale traders doing on Hyperlid right now? Give me their aggregate net
38:3438 minutes, 34 secondsexposure, the three most crowded longs, and any wallet that flipped direction in the last 24 hours. Keep it tight. I want
38:4138 minutes, 41 secondsto read this in 60 seconds. Watch as Claude parses thousands of data points, groups them by asset, and spits out a
38:4938 minutes, 49 secondshigh signal report. You now know exactly where the smart money is positioned before you ever place a trade. In the notes, I've given you seven signature
38:5738 minutes, 57 secondsprompts to steal. These are the exact ones I run every morning. Use smart money versus wrecked money to see where the winners and losers disagree. That is often where the asymmetric setup lives.
39:0839 minutes, 8 secondsUse the morning alpha scan to see what happened overnight while you were sleeping. Copy these into your clawed MD file under a favorites heading. That way, they're always just one click away.
39:2039 minutes, 20 secondsYour workflow just change forever. No more Twitter bias or guessing. You are building your trade ideas on hard data.
39:2839 minutes, 28 secondsYou know what the whales hold before you decide your own direction, but research is only half the battle. You still need to see the charts. I'll see you in
39:3639 minutes, 36 secondsmodule 10 where we give Claude control over your Trading View. In this module, we will unlock the single best skill in
Chapter 12: MODULE 10: TradingView MCP
39:4339 minutes, 43 secondsthe entire course. We are installing the Trading View MCP. Up until now, Claude has been smart, but it's been blind. It
39:5139 minutes, 51 secondshad to rely on you to tell it what the charts look like. With these 78 new tools, Claude stops guessing and starts engineering. It can now read candles
39:5939 minutes, 59 secondsdirectly, write and debug Pinescript, V6, run back tests, and this is the game changer. Auto optimize your strategies
40:0740 minutes, 7 secondswhile you go get a coffee. What does 78 tools actually mean? It means Claude can switch symbols and time frames, add indicators, and pull the full report
40:1540 minutes, 15 secondsfrom the strategy tester. It doesn't just see a chart, it sees an editable canvas. If a strategy isn't working, Claude can iterate on the code and
40:2440 minutes, 24 secondsretest it until it finds a profit factor that meets your standards. Let's get the repo onto your machine. Open your terminal and run this prompt. During the
40:3340 minutes, 33 secondsinstall, you might see a playright prompt. Say yes and let it install. This is the automation engine that allows Claude to drive the browser. Now, we
40:4140 minutes, 41 secondshave to tell Claude where the server lives. You're going to open your mcp.json JSON file in yourclaw folder
40:4940 minutes, 49 secondsand merge the block from the course notes. Make sure you replace the absolute path with the real location of the folder on your computer. If you're
40:5740 minutes, 57 secondson a Mac, just type pwd inside the folder to get the exact string. This tells Claude, "When I ask for a chart,
41:0441 minutes, 4 secondsuse this specific engine to go get it." To let Claude control your charts, we have to launch a debug version of Chrome. The repo handles this for you
41:1241 minutes, 12 secondswith helper scripts. If you're on Mac, run this. If you're on Windows, use this. This will open a new Chrome window. Log into Trading View and keep
41:2141 minutes, 21 secondsthis tab open. This is the bridge Claude uses to reach into the chart. Let's see the real power. We are going to ask Claude to not only write a strategy, but to brute force the best settings for us.
41:3341 minutes, 33 secondsClaude will write a dual EMA crossover strategy. Then, it will systematically run dozens of variations, changing the
41:3941 minutes, 39 secondsfast EMA, the slow EMA, and the ATR multiplier. It will rank them by profit factor and handed you the top five
41:4741 minutes, 47 secondswinning variants with their exact inputs. You just did a week's worth of manual back testing in under five minutes. You now have 78 tools at your
41:5541 minutes, 55 secondsdisposal. Your stack is complete. You have the reasoning core, the whale tracker for onchain alpha, and the trading view mcp for technical mastery.
42:0442 minutes, 4 secondsI'll see you in module 11 where we combine all three into your daily alpha brief. Your agent can now read charts and track whales, but it's still missing
Chapter 13: MODULE 11: Firecrawl MCP
42:1342 minutes, 13 secondsone thing, the news. To trade at a high level, your AI needs to see what's happening on the open web. From Coin
42:1942 minutes, 19 secondsGecko and earnings calls to FOMC minutes and exchange blog posts, we're using Firecrawl because it does something incredible. It takes any messy URL and
42:2942 minutes, 29 secondsturns it into clean, machine readable markdown. It strips away the ads and the clutter, handing Claude exactly the data
42:3642 minutes, 36 secondsit needs to make a decision. First, head over to firecrawl.dev.
42:4042 minutes, 40 secondsCreate a free account. The free tier is more than enough to follow along with this course. Grab your API key. It'll start with FC-ash. Copy that key and put
42:4942 minutes, 49 secondsit into your password manager. We are about to wire it directly into your claw desktop. Open claw desktop. Inside this, you're going to merge the firecrawl
42:5842 minutes, 58 secondsblock from the course notes. Paste in your API key. Save the file and fully quit clawed desktop. You should now see
43:0543 minutes, 5 secondsnew superpowers like firecrawl, scrape, crawl, and search. Claude can now officially browse the internet. Let's prove the pipeline works. Give Claude
43:1443 minutes, 14 secondsthis prompt. Use firecrawl scrape on the Coin Gecko Bitcoin page and return the current price, 24-hour volume, and the top three exchanges. Watch how it works.
43:2543 minutes, 25 secondsClaw doesn't just guess the price based on its training data. It reaches out to the live site, reads the current numbers, and summarizes them for you in
43:3343 minutes, 33 secondsseconds. Firecrawl's powerful, but you have to use it strategically. If you need onchain data, stick with the whale
43:4043 minutes, 40 secondstracker. If you need price action, use the Trading View MCP. But if you need news, earnings reports, or project documentation, that's where you call
43:4943 minutes, 49 secondsFirecrawl. Don't waste your credit scraping static information like Wikipedia that Claude already knows. Use Firecrawl for live data that moves
43:5743 minutes, 57 secondsmarkets. I've included three prompts in the notes that are absolute game changers. Use the macro pulse to scrape the latest Federal Reserve statement and
44:0644 minutes, 6 secondshave Claude rate how hawkish it sounds on a scale of 1 to 10. Use the news digest to pull the last six articles
44:1344 minutes, 13 secondsfrom a major crypto news site and summarize only the ones that could move the market in the next 24 hours. Your intelligent stack is officially
44:2144 minutes, 21 secondscomplete. You have the reasoning core, the whale tracker, the chart vision, and now web access. In the next module, we
44:2944 minutes, 29 secondsare going to combine all of these into the holy grail of this course, the daily alpha brief. This is the moment everything you've installed starts
Chapter 14: MODULE 12: Daily Alpha Brief
44:3744 minutes, 37 secondstalking to each other. We are moving past tools and into a system of intelligence. The daily alpha brief is a
44:4544 minutes, 45 secondssingle master prompt that chains weeks, the whale tracker, the trading view mcp and fire crawl into one morning
44:5244 minutes, 52 secondsbriefing. This isn't just a summary. It is the research loop that replaces your entire doom scroll routine. In under two
44:5944 minutes, 59 secondsminutes, it tells you exactly what to watch, why you're watching it, and what size you should trade. Up to this point, we focus on research. No trades fired.
45:0745 minutes, 7 secondsThat's intentional. You want your agent to understand the market before it touches your money. The daily alpha brief provides four distinct layers of
45:1545 minutes, 15 secondstruth. The macro layer, Fed chatter, and overnight news via firecrol. The onchain layer, smart money positioning via the
45:2245 minutes, 22 secondswhale tracker. The technical layer, trend and support and resistance via trading view. The portfolio layer, your
45:3045 minutes, 30 secondscurrent risk and available margin via the weak skill. When these four talk to each other, hallucination liquidations disappear. I provided the master prompt
45:3945 minutes, 39 secondsin the notes below. This is your daily ritual. When you paste this into Claude code, you're going to see a symphony of tool calling. Claude will scrape the
45:4745 minutes, 47 secondsheadlines, aggregate whale exposure, read the 4hour charts for Bitcoin and Salana, and check your actual account
45:5445 minutes, 54 secondsbalance. It then synthesizes all of that into a single trade plan. It picks the highest conviction setup, sizes it based
46:0246 minutes, 2 secondson your account risk, and outputs the exact order you need to place. We don't want to copy paste this every morning.
46:0846 minutes, 8 secondsWe want efficiency. Take that prompt and drop it into your claude.md file under the heading /dailyalpha.
46:1646 minutes, 16 secondsNow you can just type /daily alalfpha in your terminal and claude will execute the entire chain automatically. You've just turned a complex multi-tool
46:2546 minutes, 25 secondsworkflow into a single keystroke. Once you've lived with this for a week, you can start upgrading the brief. You can pipe the text into 11 lab so your AI
46:3446 minutes, 34 secondsreads the market to you while you're making coffee. You can ask Claude to assign a confident score from 1 to 10 and only show you setups that are a
46:4146 minutes, 41 secondsseven or higher. You can even have Claude append every brief to a markdown journal, making your research fully auditable over time. You're no longer a retail trader guessing at the next move.
46:5246 minutes, 52 secondsYou are an operator running a professional research desk. The stack is live. The brief is running. In the next section of the course, we move into
47:0047 minutesautonomous operations. I'll see you in the next module. Up until now, you've been the one triggering the AI. You type
Chapter 15: MODULE 13: Claude Routines
47:0747 minutes, 7 secondsthe command, Claude does the work. But the goal of this course is to build a system of intelligence that works while you sleep. Enter Claude routines. This
47:1647 minutes, 16 secondsis Anthropic's native cloud hosted environment. You set a crown style schedule, pick your tools, and Claude runs your logic in the background. It
47:2447 minutes, 24 secondscan email you a summary, fire an alert to your phone, or trigger an MCP side effect. This is the easiest way to make
47:3247 minutes, 32 secondsyour daily Alpha Brief completely self-driving. Head over to this site, log in with your Pro or Max account.
47:3847 minutes, 38 secondsKeep an eye on your plan limits. As of 2026, Pro users get five routine runs per day, while max users get up to 15.
47:4747 minutes, 47 secondsYou want to budget these wisely. Don't run a research scan every 5 minutes if you're on a pro plan. Save them for the high impact moments. Let's turn your
47:5547 minutes, 55 secondsmodule 12 research into a routine. We'll set this to run every weekday at 7:30 a.m. so it hits your inbox before the
48:0348 minutes, 3 secondsmarket opens. Paste this routine setting. Paste the full master prompt from the previous module. Now, instead
48:1048 minutes, 10 secondsof you asking Claude for the news, the news finds you. This routine is your radar. We'll set it to run every 2
48:1848 minutes, 18 secondshours, 247. The prompt is simple. Check the top 20 hyperlquid wallets. Only reply if a top 10 wallet opens a
48:2748 minutes, 27 secondsposition larger than $5 million or if a whale flips direction on Bitcoin. Tell Claude, "If no criteria are met, reply
48:3548 minutes, 35 secondswith the word skip." This prevents your inbox from getting cluttered with nothing to report emails. You only get notified when there is actual blood in
48:4348 minutes, 43 secondsthe water. This is the most important routine you'll ever set up. It's a safety net. Set this to run every hour
48:5048 minutes, 50 secondsduring your active trading window. It pulls your open positions across Weeks, Alpaca, and Interactive Brokers. It
48:5848 minutes, 58 secondscalculates your total open risk and checks for any position missing a stop-loss. If you've drifted past your 2% risk limit, Claude flags it
49:0649 minutes, 6 secondsimmediately. It's the unsexy work that keeps you in the game. So, when do you use a routine versus a local script?
49:1349 minutes, 13 secondsClawed routines are perfect for a read and report task. They require zero infrastructure and run even if your laptop is at the bottom of a lake.
49:2249 minutes, 22 secondsHowever, if you want to run arbitrary Python code or place complex automated orders without a human in the loop,
49:3049 minutes, 30 secondsyou'll need a VPS. We're going to build that protier setup in module 24 using Hostinger. For now, set up your first
49:3749 minutes, 37 secondsthree routines. Let the AI start doing the heavy lifting. In this module, you are going to ship a full PES script version 6 strategy from plain English.
Chapter 16: MODULE 14: Pine Script
49:4649 minutes, 46 secondsWe're going to add confluence filters, drawer support, and resistance automatically and debug those frustrating red squiggles just by
49:5449 minutes, 54 secondsdescribing them out loud to Claude. We start with the clean sheet, open your terminal, launch Claude code, and give it the rules for a classic trend
50:0250 minutes, 2 secondsfollowing setup. Claude doesn't just write the code in a text box. It uses the MCP to open the Pine editor on your screen, paste the code, and compile it.
50:1250 minutes, 12 secondsIf there's an error, Claude sees it and fixes it before it ever hands the strategy back to you. A basic strategy is often too noisy. We need to filter
50:2050 minutes, 20 secondsfor high probability environments. Tell Claude to take that same strategy and add confluence filters. We'll restrict
50:2850 minutes, 28 secondstrades to the London and New York sessions. Ensure the daily trend is in our favor and crucially require a
50:3550 minutes, 35 secondsminimum amount of volatility. Claude will update the code and show you sidebyside stats. You'll see exactly how those filters affected your profit
50:4350 minutes, 43 secondsfactor and your draw down. We aren't just guessing that a filter works. We're proving it with data. Claude can also handle the visual side of the chart. We
50:5250 minutes, 52 secondscan ask it to write an indicator that auto detects the five strongest horizontal levels using pivots from the
50:5950 minutes, 59 secondslast 500 bars. Ask it to color support green and resistance red. In seconds, Claude writes the math, compiles the
51:0751 minutes, 7 secondsindicator, and publishes it directly to your live chart. You now have a customuilt technical analysis tool tailored to your specific style. When a
51:1651 minutes, 16 secondsscript won't compile, stop googling the error codes. Just copy the error message from the bottom of your Trading View screen and paste it into Claude. Claude
51:2551 minutes, 25 secondsuses the MCP to read the source code, identifies the root cause, whether it's a version mismatch or a syntax error,
51:3251 minutes, 32 secondsand recompiles the fix instantly. It's like having a senior Pine Script developer sitting right next to you.
51:3851 minutes, 38 secondsBefore you get excited about a back test, run it through the honesty filter.
51:4251 minutes, 42 secondsSample size. If the strategy has fewer than 100 trades, it's just noise. Costs.
51:4751 minutes, 47 secondsAlways tell Claude to include commission and slippage in the settings. Real trading isn't free. Repainting. Ask Claude to verify that no look ahead
51:5651 minutes, 56 secondsindicators are used. A strategy that knows the future on a back test will blow up your account in the real world.
52:0352 minutes, 3 secondsYou now have the power to engineer an edge from scratch. In this module, we are building your mobile control plane.
Chapter 17: MODULE 15: Telegram
52:1152 minutes, 11 secondsWe're going to use Telegram's botfather, install the official Telegram plugin for Claude, and pair your phone. By the end of this video, your entire trading
52:1952 minutes, 19 secondsstack, the whales, the charts, and the brokers will be accessible from a single chat window in your pocket. First, open Telegram and search forbotfather.
52:2952 minutes, 29 secondsThis is the official way to create bots. Send the command/newbot.
52:3452 minutes, 34 secondsGive it a name, something like trading ops. Give it a unique username that ends in the word bot. Botfather will hand you
52:4252 minutes, 42 secondsan API token. Copy that immediately and put it in your password manager. This is the key that lets Claude log into your
52:4952 minutes, 49 secondsTelegram account. Now go back to your terminal and launch Claude Code. We're going to install the official plugin
52:5652 minutes, 56 secondsusing /comands. Type /plugin install Telegram and then /reload-plugins.
53:0253 minutes, 2 secondsFinally, run the configuration command and paste in that token you just got from Botfather. You've just successfully linked the brain to the messenger. To
53:1153 minutes, 11 secondsmake this work, we have to relaunch Claude with the Telegram channel attached. This allows messages to flow in both directions. Close your current
53:1953 minutes, 19 secondscloud session and run the relaunch command from the notes. You'll see a message in your terminal saying the Telegram channel is active and waiting.
53:2753 minutes, 27 secondsNow open Telegram on your phone. Find your new bot and hit start. Send it any message. Claude will print a six character pair code in your terminal.
53:3553 minutes, 35 secondsPaste that back into Claude to lock the connection. Then set the access policy to allow list. This is critical. It
53:4253 minutes, 42 secondsensures that only your paired phone can drive the agent. If anyone else finds your bot and tries to issue a trade, they'll be denied instantly. Let's see
53:5053 minutes, 50 secondswhat this actually looks like in the real world. Imagine you're out for dinner and you want a whale flash. You just text the bot, "Any top 20 wallet
53:5853 minutes, 58 secondsflips in the last 2 hours?" Claude scans the chain and texts you back in seconds.
54:0454 minutes, 4 secondsWant to check your book? Ask what's open on weeks right now and get your P&L delivered as a message. You can even execute trades. Tell Claude, "Propose a
54:1354 minutes, 13 secondsBitcoin long." Claude will do the math and wait. It won't fire until you reply with the word go. This human in the loop
54:2054 minutes, 20 secondssafety rail is what keeps you from making accidental fat finger trades from your pocket. You're now a mobile first operator. You have the full power of a
54:2954 minutes, 29 secondsprofessional research and execution desk condensed into a chat app. In the next module, we're going to dive into advanced agentic workflows. This is the module where the thing actually trades.
Chapter 18: MODULE 16: TradingView x WEEX Webhook
54:4054 minutes, 40 secondsWe are building the full automated pipeline. Trading View fires an alert.
54:4454 minutes, 44 secondsEnro forwards it to your local server and Claude acts as the final decision layer to place a risksiz order on Wix.
54:5154 minutes, 51 secondsFully automatic, fully auditable. No more manual entry. Think of this like a digital relay race. Your Pine script
54:5854 minutes, 58 secondsfires an alert with a JSo payload. The Trading View web hook sends that data to your Enro URL. Your Flask receiver, a
55:0655 minutes, 6 secondstiny Python server, catches the alert and triggers Claude. Claude using the Wixx skill reads the data, applies your risk rules, and fires the order.
55:1555 minutes, 15 secondsConsistency is everything in automation.
55:1855 minutes, 18 secondsWe use a standardized JSo schema. It includes the symbol, the side, the price, and your specific risk parameters like leverage and stop-loss percentages.
55:2855 minutes, 28 secondsCopy the schema from the notes. This is the language your alert will speak to Claude. We aren't going to write this Flask server line by line. We're going
55:3555 minutes, 35 secondsto let Claude scaffold it. Paste the prompt from section 16.3 into your terminal. Claude will create tv webhook.
55:4355 minutes, 43 secondspy. This script does three things. It validates the incoming alert, logs it to a file, and then shells out to the Wix
55:5155 minutes, 51 secondsskill to execute the trade. Notice that we aren't bypassing Claude. Claude remains the brain that decides exactly how to size the position before the
56:0056 minutesorder hits the exchange. Trading View lives in the cloud, but your flash server lives on your laptop. To bridge that gap, we use Enro. In your terminal,
56:0856 minutes, 8 secondsrun enro http 50005. This creates a secure tunnel from the open web directly
56:1556 minutes, 15 secondsto your machine. Copy that enropp URL. That is now your official web hook
56:2256 minutes, 22 secondsendpoint. Now go to your trading view chart. Open the strategy we built in module 14 and click the alarm icon. In the message box, paste your JS payload.
56:3256 minutes, 32 secondsIn the web hook URL, paste your new end Grock address. Set the trigger to once per bar close. The first time your
56:4156 minutes, 41 secondsstrategy conditions are met, the whole pipeline will fire. Do not scale this immediately. Run your first 10 alerts on a tiny $50 test account. Watch it. Place
56:5056 minutes, 50 secondsthe entry, the stop-loss, and the takerit correctly. Only once you've audited the logs and seen it work end to end do you move to your main book. You
56:5956 minutes, 59 secondshave just closed the loop. You are no longer chatting with an AI. You have built an autonomous execution engine that responds to market data in real
57:0857 minutes, 8 secondstime. In the next module, we're going to look at one of the most profitable corners of the market, prediction markets. This is where things get truly
Chapter 19: MODULE 17: Prediction Markets
57:1657 minutes, 16 secondsinteresting. We are moving beyond price action and into the world of prediction markets. This is the home of the legendary $3 million bot, and today
57:2557 minutes, 25 secondswe're building our own. Prediction markets allow you to bet on real world outcomes. politics, Fed decisions, even
57:3357 minutes, 33 secondsthe weather. We're going to use Poly Market, which runs on Polygon using USDC and KHI, the US regulated venue. We're
57:4157 minutes, 41 secondsgoing to build a sovereign analyzer that uses Claude Opus 4.7 to research the news, calculate the odds, and stake real bets. Poly Market is the global giant.
57:5157 minutes, 51 secondsIt handles billions in monthly volume.
57:5457 minutes, 54 secondsBecause it's decentralized and uses a central limit order book, it has the deepest liquidity for crypto and pop
58:0058 minutesculture events. Khi is the protier CFTC regulated venue. It's funded in US dollars and is the gold standard for
58:0858 minutes, 8 secondsmacro events like CPI prints and Federal Reserve meetings. Both offer open APIs, which means Claude can price shop between them to find the best edge.
58:1858 minutes, 18 secondsLet's get your credentials ready for Poly Market. Connect your MetaMask or Coinbase wallet and fund it with USDC on the Polygon network. You'll need to copy
58:2758 minutes, 27 secondsyour private key and your wallet address into your ENV file. Then install the client by running pip install prompt for
58:3458 minutes, 34 secondsKshi. Complete your KYC and fund it with USD. You'll need to generate an RSA key pair in their API settings. Install
58:4258 minutes, 42 secondstheir SDK with pip install prompt as well. Now the main event, we are going to live build analyzer. py using claude
58:5058 minutes, 50 secondscode. We're telling Claude to build a script that takes a polyarket URL as an input. It will fetch the current odds,
58:5758 minutes, 57 secondsthen use claude opus 4.7 with the web search enabled to find the latest news.
59:0259 minutes, 2 secondsClaude will then return a JSON in response with a yes or no decision and a confidence score. Notice the confidence
59:1059 minutes, 10 secondsgate. We tell the bot if confidence is high, bet $5. If it's medium, bet two.
59:1659 minutes, 16 secondsIf it's low, skip it entirely. This gate is what prevents your bot from overtrading on noise. The real alpha
59:2359 minutes, 23 secondslives in the gaps. Poly market and couchi often list the same event like will the Fed cut rates in June at
59:3059 minutes, 30 secondsdifferent prices. We use the PMXT library to unify both markets. This allows Claude to see both order books at
59:3759 minutes, 37 secondsonce. If one market is at 60 cents and the other is at 65, your bot can buy the cheap side and lock in a nearly
59:4459 minutes, 44 secondsrisk-free profit. Before you go live, keep your dry run flag set to true.
59:5059 minutes, 50 secondsWatch the logs for a few days. Arbitrage looks pristine in a screenshot, but in the real world, gas fees and slippage eat your margin. You now have an agent
59:5959 minutes, 59 secondsthat understands a world as well as it understands the charts. We have spent this course building a deep custom infrastructure. But sometimes you just
Chapter 20: MODULE 18: Agent PNL
1:00:081 hour, 8 secondswant to test a theory now. You want to go from an idea in your head to a live order on the exchange in under 120 seconds. That is what agent PNL is for.
1:00:181 hour, 18 secondsIt is the absolute easiest way to get a week's trading agent running. You write your strategy in plain English, pick your model, and hit start. Your bot
1:00:271 hour, 27 secondstrades weeks perpetuals on its own, and it performance shows up live on a public leaderboard. The best part, you don't have to take anyone's word for it. Every
1:00:351 hour, 35 secondsbot on the agent PNL leaderboard is verifiable directly on the WEX exchange.
1:00:401 hour, 40 secondsYou aren't looking at a photoshopped screenshot. You can click through to the actual trade logs. It's a level of transparency that is rare in the world
1:00:481 hour, 48 secondsof cryptobots. Let's do a live run. Head over to agentpnl.io.
1:00:541 hour, 54 secondsConnect your week's account using those API keys we generated back in module 5.
1:00:581 hour, 58 secondsNow for the strategy, you don't need to code. Just paste your logic in plain English. Pick your model. Claude 3.5.
1:01:061 hour, 1 minute, 6 secondsSonnet is the gold standard here. Hit start. That's it. Your bot is now live.
1:01:111 hour, 1 minute, 11 secondsIt's scanning the markets, managing your risk, and its P&L is streaming to the leaderboard in real time. Even if you prefer building your own custom Python
1:01:191 hour, 1 minute, 19 secondsbots, agent PNL is a massive asset for three reasons. The benchmark. You can compare your custom strategies against public bots running on the same venue.
1:01:301 hour, 1 minute, 30 secondsThe sandbox. It's the perfect place to paper test a new idea without setting up any of your own servers. Social Alpha,
1:01:381 hour, 1 minute, 38 secondsthe leaderboard, is a live read on what's actually working in the current market. If a specific bot is crushing it, you can study its logic and even
1:01:461 hour, 1 minute, 46 secondscopy trade it. Now, let's be real about the trade-offs. Because this is a noode platform, it's less flexible than the
1:01:541 hour, 1 minute, 54 secondscustom Python agents we build later in the course. If you need 10 different data sources and a complex MCP stack,
1:02:011 hour, 2 minutes, 1 secondyou'll outgrow this. Also, remember your strategy is running on their servers, not yours. Now that you've seen the easiest way to trade Weeks, let's look at the powerhouse for Hyperlid.
Chapter 21: MODULE 19: Senpi
1:02:121 hour, 2 minutes, 12 secondsIf Weeks is our primary crypto home, Hyperlid is our primary onchain home. To dominate the ecosystem, you need a
1:02:201 hour, 2 minutes, 20 secondsspecialist. Enter Senpi. Senpi is a turnkey personal trading agent built specifically for Hyperlquid. It packs 44
1:02:271 hour, 2 minutes, 27 secondsspecialized MCP tools, persistent memory, and built-in Telegram alerts.
1:02:321 hour, 2 minutes, 32 secondsThis system has already processed over $100 million in volume. Under the hood, it's powered by OpenClaw, but today
1:02:401 hour, 2 minutes, 40 secondswe're going to focus on getting it live in minutes. The easiest way to keep Senpe running 24/7 is via Railway. One,
1:02:481 hour, 2 minutes, 48 secondsgo to Senpe.ai and generate an authorization token. Two, head over to railway.app and use the senpai template.
1:02:571 hour, 2 minutes, 57 secondsThree, you'll need to fill in six environment variables, including your open router key and your hyperlquid private key. Set your strategy
1:03:051 hour, 3 minutes, 5 secondsparameters to a conservative 1% risk and five times leverage while you're testing. Once you hit deploy, Rearway builds the agent in the cloud. You can
1:03:141 hour, 3 minutes, 14 secondsclose your laptop and senpai will stay on the hunt. If you prefer to keep your keys on your own machine, you can install the senpai skill bundle directly
1:03:221 hour, 3 minutes, 22 secondsinto Claude Code. Open your terminal and clone the repository. Copy the skills into your specialized.claude skills
1:03:301 hour, 3 minutes, 30 secondsdirectory and relaunch Claude. You now have the exact same 44 tools from opportunity scanners to wallet trackers available right in your local terminal.
1:03:401 hour, 3 minutes, 40 secondsLet's see what 44 specialized tools can actually do. Ask Senpe to rank every trader by ROI and consistency. It
1:03:471 hour, 3 minutes, 47 secondsdoesn't just look at P&L, it looks at the quality of the trading. Run the opportunity scanner to see which assets have smart money accelerating up the
1:03:561 hour, 3 minutes, 56 secondsranks. or go full alpha and ask senpai to build a copy trading strategy that mirrors the top three traders on the leaderboard with a 5% safety stop. You
1:04:051 hour, 4 minutes, 5 secondsaren't just trading against the market anymore. You are standing on the shoulders of the most profitable giants in the ecosystem. Seni also features a
1:04:131 hour, 4 minutes, 13 secondsweekly arena. This is where agents go head-to-head. Every trade you make earns you points. Two points for every dollar
1:04:211 hour, 4 minutes, 21 secondsvolume. Even if you don't care about the prizes, watch the arena replays. It is the best way to see how top tier AI
1:04:281 hour, 4 minutes, 28 secondsagents reason under extreme market pressure. It's a masterclass in agentic logic. You now have a dedicated hyperlquid specialist. Whether it's
1:04:371 hour, 4 minutes, 37 secondsrunning in the cloud or on your desk, you have the most advanced tools available for onchain trading. In the next module, we're going to look at
1:04:451 hour, 4 minutes, 45 secondsHermes, the framework that allows your agents to learn and grow on their own.
Chapter 22: MODULE 20: Hermes
1:04:501 hour, 4 minutes, 50 secondsWe've built execution bots and research assistants, but now we're installing the professor of our stack. Hermes is an open- source Python framework from Noose
1:04:581 hour, 4 minutes, 58 secondsResearch. It has nearly 100,000 stars on GitHub and a massive community behind it. But for us, only one feature
1:05:051 hour, 5 minutes, 5 secondsmatters, persistent memory. While other agents might forget what you talked about yesterday, Hermes remembers your prompts, your trade history, and your
1:05:141 hour, 5 minutes, 14 secondsjournals across every single session. It is the most alive feeling agent in this entire course. Let's get Hermes onto your machine. We're going to use the
1:05:221 hour, 5 minutes, 22 secondsofficial setup script because it handles the heavy lifting. It installs a tool called UV for speed, creates a virtual environment, and links their Hermes
1:05:311 hour, 5 minutes, 31 secondscommand line interface directly to your system. Open your terminal and clone the repo. Run this prompt. Once that's done,
1:05:381 hour, 5 minutes, 38 secondsyou can call Hermes from anywhere on your machine just by typing its name.
1:05:431 hour, 5 minutes, 43 secondsNow run Hermes setup. This is where we wire the brain. Select Open Router as your provider. Use the same master key
1:05:501 hour, 5 minutes, 50 secondswe generated in module 4. Pick Claude Senate 4.6 as your default model. Finally, enable the Telegram gateway.
1:05:581 hour, 5 minutes, 58 secondsOne of Hermes unique strengths is its flexibility. If you don't like Telegram, you can bridge Hermes into Discord, Slack, or even WhatsApp. It meets you
1:06:071 hour, 6 minutes, 7 secondswherever you do your work. There are four commands you need to know. Hermes.
1:06:121 hour, 6 minutes, 12 secondsIt drops you into a live conversation where memory is always active. Hermes tools. This is where you add or remove
1:06:191 hour, 6 minutes, 19 secondscapabilities. Hermes gateway. This starts the bridge to your messaging apps. Hermes Doctor. If an integration
1:06:261 hour, 6 minutes, 26 secondsfails or a key goes missing, run the doctor. It's the fastest way to diagnose your system. By default, Hermes is a standard agent. To make it
1:06:341 hour, 6 minutes, 34 secondsself-learning, we need to edit the config file. Open your config.ML and flip persistent memory and skill
1:06:421 hour, 6 minutes, 42 secondsgeneration to true. Now, when Hermes successfully completes a complex task like writing a new arbitrage script, it
1:06:491 hour, 6 minutes, 49 secondssaves that logic as a reusable skill. It literally gets smarter the more you use it. You might be wondering, if I have
1:06:561 hour, 6 minutes, 56 secondsclawed code, why do I need Hermes? Two reasons. First, open runtime. If Anthropic ever hits you with rate limits
1:07:041 hour, 7 minutes, 4 secondson a high volatility day, Hermes keeps running through any of the 300 models on Open Router. Second, the journal. Hermes
1:07:121 hour, 7 minutes, 12 secondsis built to store long-term trade journals. It can look back at six months of your trades and identify patterns in your behavior that you might have
1:07:191 hour, 7 minutes, 19 secondsmissed. You now have an agent that doesn't just trade, it studies. In the next module, we're going to look at the engine behind it all, OpenClaw. We are
Chapter 23: MODULE 21: OpenClaw
1:07:281 hour, 7 minutes, 28 secondsnow looking at the Titan of the ecosystem. OpenClaw is the largest open-source clawed compatible agent
1:07:351 hour, 7 minutes, 35 secondsruntime on the planet. As of April 2026, it has over 360,000 stars on GitHub, a massive plug-in
1:07:441 hour, 7 minutes, 44 secondsmarketplace called Clawhub, and a high performance TypeScript design. But with massive reach comes massive risk. In
1:07:511 hour, 7 minutes, 51 secondsMarch of 2026 alone, nine major security vulnerabilities were disclosed, including remote code execution. Even
1:07:581 hour, 7 minutes, 58 secondsworse, independent audits found that up to 20% of the plugins on Clawhub are shipping malware or credential stealers.
1:08:051 hour, 8 minutes, 5 secondsIn this module, we're going to benefit from this massive ecosystem while ensuring your trading keys never leave
1:08:121 hour, 8 minutes, 12 secondsyour machine. OpenClaw is a Node.jsbased system. Run the install command in your terminal, but pay attention to the
1:08:201 hour, 8 minutes, 20 secondsversioning. Never track the latest version in a production environment.
1:08:251 hour, 8 minutes, 25 secondsThat is how supply chain attacks reach you. Pick a known good stable version like the one listed in the course notes
1:08:321 hour, 8 minutes, 32 secondsand pin it. When you run openclaw start, the onboarding wizard will walk you through your open route of keys and messaging channels. Before you install a
1:08:401 hour, 8 minutes, 40 secondssingle plugin, you need to understand the threats. Threat class A is credential theft. Agents have to read your B files and wallet keys to work. A
1:08:501 hour, 8 minutes, 50 secondsmalicious plug-in can stream those keys to a remote server in milliseconds.
1:08:541 hour, 8 minutes, 54 secondsThreat class B is unauthorized trades. A charting plugin that asks for exchange permissions could drain your entire week's account while you're asleep.
1:09:021 hour, 9 minutes, 2 secondsTreat Clawhub like a dark alley marketplace. Do not install anything blindly. From this point forward, you follow a strict checklist for every
1:09:101 hour, 9 minutes, 10 secondsplugin. Verify publishers only. Only install plugins with the blue check badge. Permission scrutiny. If a
1:09:171 hour, 9 minutes, 17 secondsnewsreading plugin asks for shell access, it is a virus. Deny it. Sandbox everything. Never run openclaw on your
1:09:251 hour, 9 minutes, 25 secondsmain development account. Run it as a dedicated lowprivilege user on your machine. If managing security patches sounds like a full-time job you don't
1:09:341 hour, 9 minutes, 34 secondswant, use oneclaw. This is the manage our SAS version of the platform. The core team handles the CVE patches and
1:09:421 hour, 9 minutes, 42 secondsaudits the plug-in shelf for you. You lose some open-source street cred, but you gain a dramatically smaller attack surface for your money. Here is the
1:09:501 hour, 9 minutes, 50 secondsultimate pro move. You don't have to choose between security and features.
1:09:551 hour, 9 minutes, 55 secondsYou can use Hermes which is Pythonbased and safe as your brain and use OpenClaw only as a specialist tool for specific
1:10:021 hour, 10 minutes, 2 secondsplugins. By using the agent communication protocol or ACP, you can run them side by side. You simply allow
1:10:101 hour, 10 minutes, 10 secondslist the specific verified OpenClaw plugins that Hermes is allowed to talk to. This is defense and depth. Even if
1:10:171 hour, 10 minutes, 17 secondsan OpenClaw plugin goes rogue, it physically cannot touch the rest of your system. You now have the keys to the largest AI agent library in existence.
1:10:271 hour, 10 minutes, 27 secondsAnd more importantly, you have the armor to survive it. In the next module, we're going to look at advanced prompt engineering to make these agents even
1:10:351 hour, 10 minutes, 35 secondssharper. Trying to get one giant prompt to handle research, risk, and execution is exactly how accounts get blown up. In
Chapter 24: MODULE 22: Agentic Bots with Hermes + OpenClaw
1:10:421 hour, 10 minutes, 42 secondsa real production environment, you don't use a generalist, you use specialists.
1:10:471 hour, 10 minutes, 47 secondsToday, we are separating the job into three distinct agents. We'll use OpenClaw as the orchestrator to coordinate the plan and Hermes as the
1:10:561 hour, 10 minutes, 56 secondsexecutive to handle the repeatable loops. They'll talk to each other over the ACP protocol. Together, they form a risk guardian system that protects your
1:11:051 hour, 11 minutes, 5 secondscapital while you hunt for alpha. We're building a threeperson team inside your machine, the alpha scanner. This agent reads the chain data, the charts, and
1:11:141 hour, 11 minutes, 14 secondsthe news. It outputs ranked trade ideas as JSo N. But crucially, it is physically incapable of placing an
1:11:211 hour, 11 minutes, 21 secondsorder. The risk guardian. This is a stateless veto layer. It checks your total risk and looks for news blackouts like an upcoming Fed meeting. It only
1:11:301 hour, 11 minutes, 30 secondshas two words in its vocabulary. Approve or reject. The execute weak signal. This agent only listens to the Guardian. If
1:11:381 hour, 11 minutes, 38 secondsand only if a signal is approved, it calls a weak skill to fire the trade.
1:11:421 hour, 11 minutes, 42 secondsFor these agents to work together, they need to speak the same language. We use a standardized signal JS ON shape. It
1:11:501 hour, 11 minutes, 50 secondscontains everything. The entry, the stop, the confidence score, and the rationale. Because both Claude and Hermes validate this schema before
1:11:581 hour, 11 minutes, 58 secondsacting, hallucinated trades are filtered out at the door. If the data doesn't fit the shape, the machine doesn't move. In
1:12:051 hour, 12 minutes, 5 secondsthe course notes, I provided the system prompts for all three. Your alpha scanner is programmed to run every 30 minutes. Your risk guardian is the
1:12:141 hour, 12 minutes, 14 secondsenforcer. It rejects any trade if your total account risk is over 6% or if there's a major CPI report in the next
1:12:221 hour, 12 minutes, 22 seconds90 minutes. Your executive is the soldier. It doesn't generate ideas. It just follows orders that have been stamped with a guardian approved status.
1:12:311 hour, 12 minutes, 31 secondsNow, where do these agents live? Open claw runs the alpha scanner and the risk guardian. It's the perfect orchestrator for pulling from firecrawl and trading
1:12:391 hour, 12 minutes, 39 secondsview. For the Guardian, we can even use a smaller model like Haiku 4.5. It's fast, cheap, and more than enough for
1:12:461 hour, 12 minutes, 46 secondslogic checks. Hermes runs the execution agent. Because Hermes has a learning loop, it actually gets better at hitting your fills and managing the Wix skill
1:12:551 hour, 12 minutes, 55 secondsthe more it trades. All three communicate over the ACP bridge we built in module 21. This setup allows you to
1:13:021 hour, 13 minutes, 2 secondsfan out your signals to multiple channels. You could have a private Telegram for your own trades and a public alpha feed for your community,
1:13:101 hour, 13 minutes, 10 secondsall driven by the same brain. You have transitioned from a single bot to a sovereign trading desk. Your risk is managed, your execution is specialized,
1:13:191 hour, 13 minutes, 19 secondsand your research is automated. In the next module, we're going to look at the custom code layer, the CCXT bridge.
Chapter 25: MODULE 23: Scaffolding Python Trading Bot
1:13:271 hour, 13 minutes, 27 secondsAgents are incredible for research and complex decision-making. But for the tight interloop, the momentto- moment
1:13:341 hour, 13 minutes, 34 secondscheck of price just ticked. Should I move my stop? You want old school optimized code. In this module, we're
1:13:411 hour, 13 minutes, 41 secondsgoing to use clawed code to scaffold a professional-grade Python bot. It will be typed, tested, and production ready.
1:13:481 hour, 13 minutes, 48 secondsIt uses the weak skill for the heavy lifting and handles the logic gates itself. This is the bridge between AI creativity and software stability. Our
1:13:571 hour, 13 minutes, 57 secondsshopping list is built for global access. We use CCXT which allows you to swap between weeks, bonance or Kraken
1:14:051 hour, 14 minutes, 5 secondswith a single line of code. We include Pideantic for data validation and logaru for structured logs. This ensures that
1:14:121 hour, 14 minutes, 12 secondsif the bot does something unexpected, you have a clear searchable trail of exactly why it happened. We aren't just
1:14:191 hour, 14 minutes, 19 secondscreating a single file. We are building a professional directory structure. I provided a master prompt in the notes that tells Claude to scaffold the entire
1:14:271 hour, 14 minutes, 27 secondsproject from the strategy layer to the risk guardian and the execution wrapper.
1:14:331 hour, 14 minutes, 33 secondsClaude will generate the models, wire the data fetcher, and create a make file. This means you don't have to remember complex commands. You just type
1:14:401 hour, 14 minutes, 40 secondsmake test or make run paper. Notice that we require the bot to pass its own unit test before we even attempt to run it.
1:14:471 hour, 14 minutes, 47 secondsIf the risk rules aren't working in the test, the bot won't launch. In professional trading, safety isn't a feature. It's the foundation. Default
1:14:551 hour, 14 minutes, 55 secondspaper, your bot will default to live equals false. You have to manually flip a toggle and set an environment variable
1:15:021 hour, 15 minutes, 2 secondsto risk a single dollar. The daily kill switch. If your total loss for the day hits 3%, the bot is programmed to
1:15:091 hour, 15 minutes, 9 secondsflatten all positions and exit. It protects you from yourself. The heartbeat. Every time the loop runs, the bot sends a oneline status to your
1:15:181 hour, 15 minutes, 18 secondstelegram. If your phone goes silent, you know immediately that something is wrong. Once Claude finishes the scaffold, it's time for the first run.
1:15:261 hour, 15 minutes, 26 secondsMove into your bot directory and run make install. Then make test. If you see all green, you are ready for make run paper. Let this run for at least 48
1:15:341 hour, 15 minutes, 34 secondshours in paper mode. Review every single log entry. Check every simulated fill.
1:15:401 hour, 15 minutes, 40 secondsMake sure the risk guardian rejected the trades it was supposed to. Only once the logs are boring and the math is perfect do you even think about going live. You
1:15:491 hour, 15 minutes, 49 secondsnow have a professional Python trading engine. It's clean, it's fast, and it's built to be managed by you and Claude as a team. Now that your bot is built, we
1:15:571 hour, 15 minutes, 57 secondsneed a place for it to live 24/7. Your laptop is not a production environment.
Chapter 26: MODULE 24: Hostinger VPS
1:16:011 hour, 16 minutes, 1 secondIf your Wi-Fi drops or your battery dies, your bot dies with it. To trade like a professional, your code needs to live in a hardened data center with
1:16:091 hour, 16 minutes, 9 seconds99.9% uptime. In this module, we are moving your bot to a hoster KVM2
1:16:171 hour, 16 minutes, 17 secondsVPS running Iuntu 24.04. We are going to harden your SSH access. Lock down the
1:16:251 hour, 16 minutes, 25 secondsfirewall and wrap your bot in a system service so it auto restarts if it ever crashes. Head over to this link. I
1:16:321 hour, 16 minutes, 32 secondsrecommend the KVM2 plan. This is more than enough to run your bot plus multiple clawed code sessions. When choosing a data center, think about
1:16:401 hour, 16 minutes, 40 secondslatency. Set a strong root password, but don't get too attached to it. We're going to disable it in the next step.
1:16:461 hour, 16 minutes, 46 secondsThe second your IP address hits the public internet, malicious bots will start knocking on your door. We are going to lock it down immediately.
1:16:541 hour, 16 minutes, 54 secondsCreate a dedicated user named trader.
1:16:571 hour, 16 minutes, 57 secondsUpload your SSH public key from your laptop. Disable root login and password authentication. By doing this, even if
1:17:061 hour, 17 minutes, 6 secondssomeone guesses your password, they can't get in. Only your physical laptop carrying your unique key has the badge
1:17:131 hour, 17 minutes, 13 secondsrequired to enter this server. Finally, enable the UFW firewall and only allow port 22 for your secure connection. Now,
1:17:211 hour, 17 minutes, 21 secondslog in as your new trader user. Update the system and install the Python 3.12 runtime. You're going to get clone your
1:17:281 hour, 17 minutes, 28 secondstrading repository. Create a fresh virtual environment and install your requirements. Copy your env file from
1:17:361 hour, 17 minutes, 36 secondsyour laptop to the server. Now take that VPS public IP address and go back to your Wix API settings. Whitelist this
1:17:431 hour, 17 minutes, 43 secondsspecific IP. This is your final layer of security. Your API keys will now refuse to work from any computer on Earth
1:17:511 hour, 17 minutes, 51 secondsexcept this one specific server. We don't want to run the bot manually in a terminal window. We want it to be a system service. We're going to create a
1:17:591 hour, 17 minutes, 59 secondssystem unit file. This tells this bot is a priority. If the server reboots, start the bot. If the bot crashes, wait 5
1:18:071 hour, 18 minutes, 7 secondsseconds and restart it. Once you reload the demon and hit start, your bot is officially a demon, a background process
1:18:141 hour, 18 minutes, 14 secondsthat breeds on its own. Now that the bot is invisible in the background, how do you see what it's doing? You use journal
1:18:201 hour, 18 minutes, 20 secondsctl. Type this. This gives you a live streaming view of your bot's heartbeat.
1:18:271 hour, 18 minutes, 27 secondsEvery trade, every risk check, and every API call shows up here in real time.
1:18:321 hour, 18 minutes, 32 secondsYour laptop is now just a remote control. Your bot is live in a professional data center. In our final module, we're going to build the glass cockpit, the personal trading dashboard.
Chapter 27: MODULE 25: Live Ops Dashboard
1:18:431 hour, 18 minutes, 43 secondsYou've done it. You've built the engine, the radar, the brain, and the safety net. But looking at 12 different terminal windows and browser tabs is not
1:18:521 hour, 18 minutes, 52 secondshow a professional operator works. You need one pane of glass. In this final module, we are building your live ops dashboard. We'll start by bootstrapping
1:19:011 hour, 19 minutes, 1 seconda high-performance HTML skeleton with the Wix skill. Then we'll fold in every other piece of the stack from alpaca
1:19:081 hour, 19 minutes, 8 secondsstocks to your whale tracker data until you have a real time glass cockpit for your entire train and empire. We're
1:19:161 hour, 19 minutes, 16 secondsgoing to let Claude code do the heavy lifting here. Use the prompt in the notes to generate a single page dashboard. We aren't using heavy
1:19:231 hour, 19 minutes, 23 secondsframeworks like React or Vue. We want speed. We're going with vanilla JavaScript, a dark theme to match our course aesthetic, and Jet Brains monitor
1:19:321 hour, 19 minutes, 32 secondsfor the numbers because precision matters. This dashboard will auto refresh every 30 seconds, showing your equity curve, your open positions, and
1:19:411 hour, 19 minutes, 41 secondsyour most recent signals from the log files. Once the skeleton is live, we start plugging in the rest of the course. One prompt at a time, you'll ask
1:19:501 hour, 19 minutes, 50 secondsClaude to add an alpaca panel for your US stocks. Add a whale pulse to see what the smart money is doing without leaving the page. Add a heartbeat panel that
1:19:591 hour, 19 minutes, 59 secondsmonitors your VPS. If that dot turns red, you know your bot has stopped. Add your Seni and agent PNL stats so you can
1:20:071 hour, 20 minutes, 7 secondssee how your autonomous agents are performing. You're not just building a website, you're building a sovereign intelligence hub. Now, where does this
1:20:151 hour, 20 minutes, 15 secondslive? If you want it for your eyes only, serve it from your Hostinger VPS using Caddy and lock it behind your IP
1:20:211 hour, 20 minutes, 21 secondsaddress. If you want a fast global URL, push it to Net Leafi. If you want to turn this into a business, you can
1:20:291 hour, 20 minutes, 29 secondsanonymize the data and gate the dashboard behind a W tier. Your proof room becomes a $29 a month subscription
1:20:361 hour, 20 minutes, 36 secondsthat sells itself. Take a look at what has changed in your life. You went from 12 browser tabs and doom scrolling Twitter for entries to one single URL.
1:20:461 hour, 20 minutes, 46 secondsEvery morning, the daily alpha brief hits your inbox while you're still in bed. Your custom bot handles the inner loop execution with a built-in risk
1:20:541 hour, 20 minutes, 54 secondsguardian. And your dashboard shows you the results in real time. You are no longer playing the markets. You have engineered a professional advantage.
1:21:031 hour, 21 minutes, 3 secondsYour computer is now a highfrequency workstation and your agents are your employees. The rest of the day, the rest of the day is yours. Congratulations.
1:21:131 hour, 21 minutes, 13 secondsYou have completed the trading AI full course. Now go out there and execute. A few hours ago, this was a blank laptop.
1:21:211 hour, 21 minutes, 21 secondsNow, it is a professional-grade AI trading stack. You have the research brain, the execution hands, the risk guardian, three brokers, and a custom
1:21:291 hour, 21 minutes, 29 secondsbot running in the cloud. This is the shortest module in the course because the work is done. This is the one that tells you exactly what to do tomorrow
Chapter 28: Outro
1:21:371 hour, 21 minutes, 37 secondsmorning. Let's look at the empire you just built. You have Claude code dialed in. Your weeks and alpaca accounts are live. Interactive Brokers is bridged.
1:21:461 hour, 21 minutes, 46 secondsYou've installed the whale tracker, the Trading View MCP, and your daily alpha brief. You have cloud routines running your research, web hooks automating your
1:21:551 hour, 21 minutes, 55 secondstrades, a custom bot hardened on a hosting or VPS, and a live ops dashboard that unifies everything. You didn't just
1:22:021 hour, 22 minutes, 2 secondswatch a course, you shipped a production system, a quick moment of transparency.
1:22:071 hour, 22 minutes, 7 secondsEvery tool in this course, from Wix to Hostinger, pays me a referral when you use my links. That's how I'm able to keep this content high velocity and high
1:22:151 hour, 22 minutes, 15 secondsproduction. When you start shipping your own strategies or building your own versions of this course, you should do the same. These are the tools we
1:22:241 hour, 22 minutes, 24 secondsactually use. They are the backbone of the industry. This is the most important part of the course. This is how your
1:22:311 hour, 22 minutes, 31 secondslife changes tomorrow morning. You've successfully delegated the grunt work of trading to the machines. If you want everything I showed you today, every
1:22:401 hour, 22 minutes, 40 secondsprompt, every skill code, every setup guide, it is all inside my private group. Link is in the description. First
1:22:471 hour, 22 minutes, 47 secondslink, everything is in there. If you found this useful, leave a like. It genuinely does help the channel.
1:22:531 hour, 22 minutes, 53 secondsSubscribe if you have not already. The system is live. The edge is yours. Now, go out there and execute. I'll see you at the top of the leaderboard. You're
1:23:021 hour, 23 minutes, 2 secondswatching charts, losing sleep, missing setups, while bots with no emotions take the trades you should have taken.
1:23:131 hour, 23 minutes, 13 secondsTrading is math. Humans feel. That's the whole problem. AI doesn't hesitate.
1:23:171 hour, 23 minutes, 17 secondsDoesn't revenge trade. Doesn't freeze at the 2 a.m. liquidation candle. It just executes the plan every single time.
1:23:261 hour, 23 minutes, 26 secondsInside AI Trade Edge, I give you the full stack. Autonomous trading agents, back- tested strategies, plugandplay
1:23:321 hour, 23 minutes, 32 secondstemplates, new tools every week. Not theory, real agents running while you sleep, while you're at the gym, while everyone else is still watching YouTube
1:23:401 hour, 23 minutes, 40 secondstutorials. Every week you wait, someone with worse charts and better systems profits. AI trade edge. First 100 spots,
1:23:491 hour, 23 minutes, 49 seconds$79.99 a month, locked in forever. After that, the price goes up permanently.
1:23:541 hour, 23 minutes, 54 secondsStop watching. Start executing. Trade Smarter with Alex Carter. Join now.
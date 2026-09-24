# DingTalk Enterprise Bot Configuration

## The DingTalk bot
Receiving messages with a DingTalk bot requires the enterprise bot capability:
https://open.dingtalk.com/document/dingstart/configure-the-robot-application

Message receiving comes in two flavors, `Http mode` (which needs a public address) and `Stream mode`. `Stream mode` is recommended.

Steps to create the application: https://open.dingtalk.com/document/dingstart/create-application

Application development > Internal enterprise application > DingTalk application > Create application > Add capability > Bot

### Add the bot

![img.png](add-dingding-bot.png)

### Configure the bot to use Stream mode

![configbot.png](configbot.png)

### Get the application credentials
![img.png](appkey.png)

### Configure the DingTalk credentials
Put the DingTalk application credentials into the configuration file
![img.png](envconfig.png)

### Publish the application
![img.png](img.png)

![img.png](group.png)

![img.png](add-group-bot.png)

### Scroll down to see the enterprise bot that was added
![img_1.png](img_1.png)

### Test the bot commands
![img_3.png](img_3.png)

# 该资料仅用来学习使用
## 学习资料答疑群, 可进群交流
![](./readme-img/1.png "标题")


# 安装
## 步骤1：点击管理扩展程序
![](./readme-img/2-1.png "标题")
## 步骤2：打开开发者模式
![](./readme-img/2-2.png "标题")
## 步骤3：将文件拖拽进入即可
![](./readme-img/2-3.png "标题")
## 步骤4：智普界面会出现，这样就配置好了
![](./readme-img/2-4.png "标题")

## JSON配置参数解析
```js
{
  "StartTime": {   // 从几点开始点击订阅按钮，这里可配置9.58 提前收集验证码
    "HOUR": 10,
    "MINUTE": 0,
    "SECOND": 0
  },
  "EndTime": {    // 从几点结束验证码的自动打开
    "HOUR": 10,
    "MINUTE": 5,
    "SECOND": 0
  },
  "IsCollectCodeLength": 1, // 控制每次发几个下单接口，比如2的话  点两次验证码，在连续发两次下单接口
  "AutoVertifyRunning": false, // 是否需要自动点击验证码，需要配合超级鹰使用，false代表不需要自动点击，true代表需要自动点击
  "useQrCodeType": 2,  // 1 使用超级鹰 2使用冰拓 3. 本地ocr服务
  "YING": {  // 超级鹰的配置参数
    "USER": "",  // 超级鹰登录账号
    "PASS2": "", // 超级鹰登录密码
    "SOFTID": "", // 超级鹰的软件id
    "CODETYPE": "9800" // 勿动
  },
  "BingKuo": {
    "USER": "",  // 冰拓登录账户
    "PASS2": "", // 冰拓登录账户密码
    "CODETYPE": "1324"
  },
  "ClickIndex": 1, // 控制点击哪个套餐  1 是lite套餐 2 是 pro套餐 3 是max套餐,
  "qrCodeTimeOut": 1000 // 避免限频增加验证码的加载时间1s  
}

```
## 可调整StartTime字段提前收集验证码，但推荐还是10.0开始避免限频
```js
{
  "StartTime": {   // 如从10.00开始收集验证码，目前也建议在10.00，目前glm限频
    "HOUR": 10,
    "MINUTE": 0,
    "SECOND": 0
  }
  "qrCodeTimeOut": 1000 // 避免限频增加验证码的加载时间1s
}
```

# 如果想配置自动点击验证码，接入本地ocr，看项目下的文档自己运行这个文件服务
![](./readme-img/3-1.png "标题")
配置本地ocr  https://{你的本地ip}:9898/click
![](./readme-img/3-2.png "标题")


# 如果想配置自动点击验证码，冰拓1元大概自动点击点击100次（接口比超级鹰慢点，个人感觉还行）
官网：https://www.bingtop.com/
配置
![](./readme-img/4-2.png "标题")
充值即可
![](./readme-img/4-1.png "标题")


如果想配置自动点击验证码，超级鹰1元大概自动点击点击35次
1）注册超级鹰
https://www.chaojiying.com/
2）购买题分
![](./readme-img/5-1.jpg "标题")
3）软件id  
![](./readme-img/5-2.jpg "标题")
4）配置即可
![](./readme-img/5-3.png "标题")



点击验证码后，中途无响应是正常的，可以观察下单接口会不断发送的，正常下单成功后会弹出支付弹层，记得出现支付码时要及时付款

![](./readme-img/6-1.png "标题")


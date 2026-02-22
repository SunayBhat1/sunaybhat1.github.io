---
title: "PureGen: Universal Data Purification for Train-Time Poison Defense via Generative Model Dynamics"
date: 2024-06-01
tags: ["adversarial robustness","data poisoning","generative models","diffusion models","deep learning"]
author: ["Sunay Bhat", "Jeffrey Jiang", "Omead Pooladzandi", "Alexander Branch", "Gregory Pottie"]
description: "Train-time data poison attacks compromise machine learning models by introducing adversarial examples during training. We propose universal data purification using EBM and DDPM dynamics that achieves state-of-the-art defense without requiring knowledge of the specific attack or classifier."
summary: "PureGen purifies poisoned training data using iterative Langevin dynamics of Energy-Based Models and Denoising Diffusion Probabilistic Models, achieving state-of-the-art poison defense with minimal impact on classifier generalization."
cover:
    image: "puregen.jpg"
    alt: "PureGen"
    relative: true
editPost:
    URL: "https://arxiv.org/abs/2405.18627"
    Text: "arXiv 2405.18627"
---

---

##### Download

+ [Paper](https://arxiv.org/abs/2405.18627)
+ [Code](https://github.com/SunayBhat1/PureGen_PoisonDefense)
+ [Medium blog post](https://medium.com/@sunay_bhat/puregen-deep-learning-poison-attack-defense-via-generative-models-7aa05caf04db)

---

##### Abstract

Train-time data poisoning attacks compromise machine learning models by introducing adversarial examples during training, causing misclassification. We propose universal data purification methods using a stochastic transform Ψ(x), implemented via iterative Langevin dynamics of Energy-Based Models (EBMs) and Denoising Diffusion Probabilistic Models (DDPMs). Our approach purifies poisoned data with minimal impact on classifier generalization and achieves state-of-the-art defense performance without requiring specific knowledge of the attack or classifier.

---

##### Citation

Bhat, Sunay, Jeffrey Jiang, Omead Pooladzandi, Alexander Branch, and Gregory Pottie. 2024. "PureGen: Universal Data Purification for Train-Time Poison Defense via Generative Model Dynamics." *arXiv preprint arXiv:2405.18627*.

```latex
@article{bhat2024puregen,
  title={PureGen: Universal Data Purification for Train-Time Poison Defense via Generative Model Dynamics},
  author={Bhat, Sunay and Jiang, Jeffrey and Pooladzandi, Omead and Branch, Alexander and Pottie, Gregory},
  journal={arXiv preprint arXiv:2405.18627},
  year={2024}
}
```

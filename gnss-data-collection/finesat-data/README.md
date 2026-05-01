# Gesture Recognition using Satellite Signal Sensing

This project implements gesture recognition using satellite signal sensing with XGBoost classification. The system compares the performance of raw satellite signals versus signals processed with inter-satellite differential techniques (FineSat).

## Dataset Description

### Overview

The dataset contains gesture data collected from satellite signal sensing, with 1000 samples across 5 different gesture classes.

### Data Files

| File | Description |
|------|-------------|
| `WO_FineSat_X.pth` | Features - Raw signals without inter-satellite differential processing |
| `WO_FineSat_Y.pth` | Labels for raw signals |
| `W_FineSat_X.pth` | Features - Signals after inter-satellite differential processing |
| `W_FineSat_Y.pth` | Labels for processed signals |

### Data Format

- **Features (X)**: Shape `(1000, 200)`
  - 1000 samples
  - 200 sampling points per gesture

- **Labels (Y)**: Shape `(1000,)`
  - Integer values from 0 to 4

### Gesture Classes

| Label | Gesture |
|-------|---------|
| 0 | Push |
| 1 | Push & Pull |
| 2 | Triangle |
| 3 | Draw 'M' |
| 4 | Star |

## Model

### Algorithm

The project uses **XGBoost (Extreme Gradient Boosting)** classifier for gesture recognition.

### Training Configuration

- **Train/Test Split**: 80% training, 20% testing
- **Data Shuffling**: Random state for reproducibility
- **Evaluation Metric**: Classification accuracy with confusion matrix visualization

### Experiments

1. **Without FineSat (W/O FineSat)**: Classification on raw satellite signals
2. **With FineSat (W/ FineSat)**: Classification on signals after inter-satellite differential processing

## Requirements

```
numpy
scikit-learn
xgboost
torch
matplotlib
seaborn
```

## Usage

1. Ensure all data files (`.pth` files) are in the same directory as the notebook
2. Open `gesture_en.ipynb` in Jupyter Notebook or JupyterLab
3. Run all cells to train models and visualize results

## File Structure

```
.
├── README.md                 # This file
├── gesture_en.ipynb          # Main notebook with English comments
├── gesture.ipynb             # Original notebook (Chinese comments)
├── WO_FineSat_X.pth          # Raw signal features
├── WO_FineSat_Y.pth          # Raw signal labels
├── W_FineSat_X.pth           # Processed signal features
└── W_FineSat_Y.pth           # Processed signal labels
```

## Results

The notebook generates confusion matrices for both experiments, allowing comparison of classification performance between raw and processed satellite signals.

# Redes Neuronales Profundas: Detalles de Entrenamiento
**Curso:** MT3006 – Robótica 2  
**Institución:** Universidad del Valle de Guatemala (UVG)  
**Referencia Principal:** Simon J.D. Prince, *Understanding Deep Learning* (MIT Press, 2023), Capítulos 4, 5, 6 y 9.

---

## 1. Motivación: ¿Por qué Deep Learning?

### 1.1. Del Teorema de Aproximación Universal a las Redes Profundas
Uno de los resultados teóricos seminales en el estudio de las redes neuronales es el **Teorema de Aproximación Universal** (*Universal Approximation Theorem*, Cybenko 1989; Hornik 1991):

> **Teorema:** Una red neuronal *feedforward* con una única capa oculta que contenga un número finito de neuronas y emplee funciones de activación continuas no lineales (como la función sigmoide o ReLU) puede aproximar cualquier función continua $f: \mathbb{R}^n \to \mathbb{R}^m$ en un subconjunto compacto de $\mathbb{R}^n$ con un error arbitrariamente pequeño, siempre que se disponga de suficientes neuronas.

Si una red superficial (*shallow*) con una sola capa oculta posee la capacidad teórica de aproximar cualquier función, surge una pregunta inmediata: **¿Por qué necesitamos redes profundas (*deep learning*)?**

La respuesta reside en la diferencia fundamental entre **existencia matemática** y **eficiencia computacional/estadística**:
1. **Maldición de la dimensionalidad:** Para aproximar funciones complejas y altamente no lineales en espacios de entrada de alta dimensión, una red superficial puede requerir un número **exponencialmente grande** de neuronas ($O(2^n)$).
2. **Eficiencia de parámetros:** Las arquitecturas profundas organizan la computación en jerarquías, permitiendo reutilizar características intermedias y reduciendo exponencialmente la cantidad de parámetros necesarios para representar la misma función.

---

### 1.2. Deep Learning vs. Machine Learning Tradicional

| Aspecto | Machine Learning Tradicional | Deep Learning |
| :--- | :--- | :--- |
| **Extracción de características (*Feature Extraction*)** | **Manual:** Ingenieros de dominio extraen manualmente descriptores (e.g., SIFT, HOG, filtros espectrales). | **Automática (*End-to-End*):** La red aprende simultáneamente las representaciones jerárquicas y la clasificación/regresión. |
| **Dependencia del volumen de datos** | El rendimiento satura rápidamente (*plateau*) aun cuando se añada más volumen de datos. | El rendimiento escala progresivamente conforme aumenta la cantidad de datos. |
| **Costo computacional** | Bajo/Moderado; se entrena eficientemente en CPU. | Alto; requiere paralelización masiva en hardware especializado (GPUs/TPUs). |
| **Interpretabilidad** | Alta en modelos lineales o árboles de decisión; las características tienen significado físico explícito. | Generalmente baja (modelo de "caja negra"), requiriendo métodos de explicabilidad *post-hoc* (Grad-CAM, SHAP). |

```
Machine Learning Tradicional:
[Entrada] ──> [Extracción Manual de Features] ──> [Clasificador / Regresor] ──> [Salida]

Deep Learning:
[Entrada] ──> [── Aprendizaje Extremo a Extremo (Features + Clasificación) ──] ──> [Salida]
```

---

### 1.3. Escalamiento: Rendimiento vs. Volumen de Datos
El comportamiento empírico de las familias de modelos según el volumen de datos sigue una jerarquía bien definida:

1. **Modelos estadísticos simples (Regresión lineal, Naïve Bayes):** Rápida saturación; no aprovechan grandes volúmenes de datos.
2. **Machine Learning tradicional (SVM, Random Forests):** Mayor capacidad inicial, pero alcanzan un límite asintótico temprano.
3. **Redes neuronales superficiales (*Shallow Neural Networks*):** Rendimiento intermedio.
4. **Redes neuronales profundas (*Deep Neural Networks*):** Su rendimiento supera a los métodos tradicionales a partir de un umbral crítico de datos y continúa mejorando mientras la capacidad del modelo y los datos sigan creciendo.

---

### 1.4. Criterios de Selección: ¿Cuándo usar Deep Learning?

```
                                 ¿Problema complejo y 
                                 datos no estructurados?
                                      /          \
                                    (Sí)         (No)
                                    /              \
                    ¿Dispones de >10k muestras      Usar ML Tradicional
                    y aceleración por hardware?     (XGBoost, SVM, etc.)
                            /          \
                          (Sí)         (No)
                          /              \
                   USAR DEEP LEARNING   Usar ML Tradicional o
                                        Transfer Learning / Preentrenados
```

* **SÍ usar Deep Learning:**
  * Gran volumen de datos ($\sim 10^4+$ ejemplos anotados).
  * Datos **no estructurados**: imágenes, señales de audio, texto libre, video, nubes de puntos.
  * Problemas con relaciones jerárquicas complejas.
  * Se prioriza la máxima exactitud predictiva sobre la interpretabilidad.
  * Se dispone de hardware adecuado (GPU con núcleos Tensor, TPU).

* **NO usar Deep Learning:**
  * Datasets pequeños (riesgo inminente de sobreajuste severo).
  * Datos **estructurados/tabulares** (bases de datos relacionales, hojas de cálculo): los árboles potenciados por gradiente (*Gradient Boosted Decision Trees* como XGBoost o LightGBM) suelen ser superiores y más rápidos de entrenar.
  * Se cuenta con un fuerte conocimiento del dominio físico/matemático para diseñar características analíticas.
  * El sistema exige explicabilidad estricta (e.g., certificación médica, decisiones crediticias, análisis forense).
  * Restricciones extremas de energía, memoria o latencia sin hardware dedicado.

---

## 2. Fundamentos de Expresividad en Redes Profundas

### 2.1. Funciones Lineales a Trozos con Activación ReLU
Considérese una red multicapa (*MLP*) donde cada neurona utiliza la función de activación **ReLU** (*Rectified Linear Unit*):
$$\text{ReLU}(z) = \max(0, z)$$

Dado que la suma ponderada de transformaciones afines combinada con la función ReLU produce funciones lineales a trozos (*piecewise linear functions*), una red con activaciones ReLU particiona el espacio de entrada $\mathbb{R}^D$ en un conjunto de regiones poliédricas conexas. Dentro de cada una de estas regiones, la red evalúa una función lineal afín distinta:
$$f(x) = A_k x + b_k \quad \text{para } x \in \mathcal{R}_k$$

---

### 2.2. Capacidad de Partición: Redes Superficiales vs. Redes Profundas

#### Red Superficial (1 capa oculta, $D$ neuronas en 1D)
Cada neurona ReLU añade exactamente un punto de inflexión (*kink*) en la recta real. En consecuencia, una capa oculta con $D$ neuronas puede dividir la entrada en a lo sumo:
$$\text{Regiones Lineales}_{\text{shallow}} = D + 1$$

*Ejemplo:* Con $D = 6$ neuronas en una sola capa oculta, se obtienen como máximo:
$$6 + 1 = 7 \text{ regiones lineales}$$

#### Red Profunda ($K$ capas ocultas, $D$ neuronas por capa en 1D)
Al encadenar capas, cada capa subsiguiente no solo añade nuevos puntos de quiebre, sino que **pliega y replica** las particiones generadas por las capas precedentes. Para $K$ capas con $D$ neuronas cada una, la cota superior del número de regiones lineales escala exponencialmente:
$$\text{Regiones Lineales}_{\text{deep}} \le (D + 1)^K$$

*Ejemplo:* Con el mismo número total de neuronas distribuidas en 2 capas de 3 neuronas ($D = 3, K = 2$):
$$(3 + 1)^2 = 4^2 = 16 \text{ regiones lineales}$$

```
Red Superficial (1 capa, 6 nodos):
x ──> [h1, h2, h3, h4, h5, h6] ──> y_hat
Total regiones: 7

Red Profunda (2 capas, 3 nodos cada una):
x ──> [h1, h2, h3] ──> [h'1, h'2, h'3] ──> y_hat
Total regiones: 16
```

> **Conclusión de Expresividad:** La profundidad proporciona una **ventaja exponencial de eficiencia**. Para generar una complejidad de partición equivalente a una red profunda de profundidad $K$, una red superficial requeriría un número de neuronas del orden de $(D+1)^K$, lo que dispararía la cantidad de parámetros a optimizar.

---

## 3. Dinámica de Entrenamiento y Optimización

### 3.1. Mini-Batches y Épocas (*Epochs*)
Para entrenar una red sobre un conjunto de datos $\mathcal{D} = \{(x_i, y_i)\}_{i=1}^N$:
* **Mini-Batch ($\mathcal{B}_r$):** Subconjunto aleatorio de tamaño $B = |\mathcal{B}_r|$ tomado del dataset total ($B \ll N$).
* **Época (*Epoch*):** Una pasada completa a través de todos los datos de entrenamiento, equivalente a procesar $\lceil N / B \rceil$ mini-lotes.

---

### 3.2. Descenso de Gradiente Estocástico por Mini-Batches (*Mini-Batch SGD*)
El valor de los parámetros (pesos y sesgos) en el paso $r+1$ se actualiza en la dirección opuesta al gradiente promedio acumulado sobre el lote $\mathcal{B}_r$:

$$W_{r+1} = W_r - \alpha \sum_{i \in \mathcal{B}_r} \frac{\partial \ell_i(W_r)}{\partial W}$$

donde:
* $W_r$: Vector o matriz de parámetros en el paso $r$.
* $\alpha > 0$: Tasa de aprendizaje (*learning rate*).
* $\ell_i(W_r) = \mathcal{L}(f(x_i; W_r), y_i)$: Pérdida evaluada en la muestra $i$.

#### Comparativa entre regímenes de gradiente:

| Método | Tamaño de Lote ($B$) | Varianza del Gradiente | Eficiencia en GPU | Capacidad de Escape de Mínimos Locales |
| :--- | :---: | :---: | :---: | :---: |
| **Batch GD (Completo)** | $B = N$ | Nula (gradiente exacto) | Pobre para $N$ masivo | Tiende a atascarse en puntos de ensilladura |
| **SGD Puro** | $B = 1$ | Muy alta (ruidoso) | Nula (no vectorizable) | Alta (demasiado errático) |
| **Mini-Batch SGD** | $16 \le B \le 512$ | Moderada y controlable | Óptima (paralelismo SIMD/Tensor) | Excelente equilibrio entre estabilidad y ruido útil |

---

## 4. Métricas de Evaluación y Matriz de Confusión

### 4.1. Métricas de Clasificación
* **Exactitud (*Accuracy*):**
  $$\text{Accuracy} = \frac{\text{Aciertos Totales}}{\text{Muestras Totales}} = \frac{TP + TN}{TP + TN + FP + FN}$$
  *Limitación:* En conjuntos de datos con clases desbalanceadas (e.g., 99% negativos), un clasificador trivial que prediga siempre negativo alcanzará un 99% de exactitud a pesar de ser inútil.

---

### 4.2. La Matriz de Confusión

| | **Clase Real: Positiva (1)** | **Clase Real: Negativa (0)** |
| :---: | :---: | :---: |
| **Clase Predicha: Positiva (1)** | **Verdaderos Positivos (TP)** | **Falsos Positivos (FP)** *(Error Tipo I)* |
| **Clase Predicha: Negativa (0)** | **Falsos Negativos (FN)** *(Error Tipo II)* | **Verdaderos Negativos (TN)** |

* **Precisión (*Precision*):** De todo lo que el modelo predijo como positivo, ¿cuánto lo era en realidad?
  $$\text{Precisión} = \frac{TP}{TP + FP}$$
* **Sensibilidad / Exhaustividad (*Recall* / *True Positive Rate*):** De todos los casos positivos reales, ¿cuántos logró detectar el modelo?
  $$\text{Recall} = \frac{TP}{TP + FN}$$
* **Puntuación $F_1$ (*$F_1$-Score*):** Media armónica entre Precisión y Recall:
  $$F_1 = 2 \cdot \frac{\text{Precisión} \cdot \text{Recall}}{\text{Precisión} + \text{Recall}} = \frac{2 TP}{2 TP + FP + FN}$$

---

### 4.3. Métricas de Regresión
Para predicciones continuas $\hat{y}_i$ frente a etiquetas reales $y_i$:

1. **Error Cuadrático Medio (*Mean Squared Error*, MSE):**
   $$\text{MSE} = \frac{1}{n}\sum_{i=1}^n (y_i - \hat{y}_i)^2$$
2. **Raíz del Error Cuadrático Medio (*Root Mean Squared Error*, RMSE):**
   $$\text{RMSE} = \sqrt{\frac{1}{n}\sum_{i=1}^n (y_i - \hat{y}_i)^2}$$
   *Ventaja:* Conserva las mismas unidades físicas que la variable objetivo $y$.
3. **Error Absoluto Medio (*Mean Absolute Error*, MAE):**
   $$\text{MAE} = \frac{1}{n}\sum_{i=1}^n |y_i - \hat{y}_i|$$

---

## 5. Partición de Datos: Train, Validation y Test Split

Para garantizar que el modelo no solo memorice los datos conocidos sino que generalice ante datos nuevos, el conjunto total de datos se subdivide estrictamente:

```
┌────────────────────────────────────────────────────────────────────────┐
│                          DATASET COMPLETO                              │
├──────────────────────────────────┬──────────────────┬──────────────────┤
│        Train Set (~70%)          │ Validation (20%) │  Test Set (10%)  │
│  Optimización de parámetros (W)  │ Hiperparámetros  │ "Validar la val" │
└──────────────────────────────────┴──────────────────┴──────────────────┘
```

1. **Train Set (~70%):** Se utiliza exclusivamente para calcular gradientes y actualizar los **parámetros** internos del modelo ($W, b$) mediante retropropagación.
2. **Validation Set (~20%):** Se utiliza para evaluar el rendimiento generalizador durante el entrenamiento y ajustar los **hiperparámetros** (tasa de aprendizaje $\alpha$, tamaño de lote, regularización $\lambda$, número de capas/neuronas, tasa de dropout).
3. **Test Set (~10%):** Se mantiene completamente aislado hasta el final. Sirve para reportar el error de generalización no sesgado ("validar la validación"). Si se toman decisiones de diseño basadas en el test set, ocurre **fuga de datos (*data leakage*)** y los resultados pierden validez estadística.

* **Validación Cruzada (*K-Fold Cross-Validation*):**
  Cuando el volumen total de datos es limitado, se divide la muestra en $K$ pliegues disjuntos. El modelo se entrena $K$ veces, usando cada vez $K-1$ pliegues para entrenamiento y 1 pliegue para validación, promediando el error resultante.

---

## 6. Diagnóstico del Modelo: El Dilema Sesgo-Varianza (*Bias-Variance Tradeoff*)

El comportamiento de la pérdida en el conjunto de entrenamiento frente al de validación es la herramienta fundamental de diagnóstico:

```
       Pérdida (Loss)
         ▲
         │ \  <-- Curva de Validación (Val Loss)
         │  \          ▲
         │   \________/│ Overfitting (Generalization Gap)
         │    \________│_____________________
         │     \       │                     
         │      \______│______ <-- Curva de Entrenamiento (Train Loss)
         │             │
         └─────────────┼────────────────────────► Épocas (Epochs)
                   Punto Óptimo
                   (Early Stop)
```

### Tabla Comparativa de Diagnóstico

| Escenario | Síntomas en Curvas de Pérdida | Diagnóstico Teórico | Soluciones Recomendadas |
| :--- | :--- | :--- | :--- |
| **Overfitting** *(Sobreajuste)* | • Train Loss muy baja.<br>• Val Loss significativamente más alta o creciente.<br>• Gran brecha (*generalization gap*). | **Alta Varianza:** El modelo memorizó el ruido aleatorio del train set en lugar de la función subyacente. | 1. Conseguir más datos anotados.<br>2. Aumentar regularización ($L_1$, $L_2$).<br>3. Aplicar *Dropout* o *Data Augmentation*.<br>4. Reducir la capacidad del modelo.<br>5. Aplicar *Early Stopping*. |
| **Underfitting** *(Subajuste)* | • Train Loss alta y estancada.<br>• Val Loss similarmente alta.<br>• Curva converge a un error inaceptable. | **Alto Sesgo (*Bias*):** El modelo carece de capacidad expresiva para capturar la estructura de los datos. | 1. Incrementar la complejidad del modelo (más capas/neuronas).<br>2. Añadir nuevas características relevantes.<br>3. Disminuir la regularización.<br>4. Entrenar por más épocas o cambiar de optimizador. |
| **Right Fit** *(Ajuste Óptimo)* | • Train Loss baja y convergente.<br>• Val Loss ligeramente superior pero paralela y estable. | **Equilibrio Óptimo:** Buen balance entre capacidad de ajuste y generalización. | Guardar los pesos (*checkpoint*) y proceder a evaluación final en el Test Set. |

---

## 7. Funciones de Pérdida Comunes (*Loss Functions*)

### 7.1. Para Tareas de Regresión

#### Error Cuadrático Medio (MSE / Pérdida $\mathcal{L}_2$)
$$\mathcal{L}_{MSE} = \frac{1}{n} \sum_{i=1}^n (y_i - \hat{y}_i)^2$$
* **Derivada analítica:** $\frac{\partial \mathcal{L}}{\partial \hat{y}_i} = -\frac{2}{n}(y_i - \hat{y}_i)$. Es suave, convexa y diferenciable en todo punto.
* **Comportamiento:** Como el error se eleva al cuadrado, errores grandes reciben penalizaciones desproporcionadamente altas, lo que la hace **muy sensible a valores atípicos (*outliers*)**.

#### Error Absoluto Medio (MAE / Pérdida $\mathcal{L}_1$)
$$\mathcal{L}_{MAE} = \frac{1}{n} \sum_{i=1}^n |y_i - \hat{y}_i|$$
* **Derivada analítica:** $\frac{\partial \mathcal{L}}{\partial \hat{y}_i} = -\frac{1}{n}\text{sign}(y_i - \hat{y}_i)$ para $y_i \neq \hat{y}_i$.
* **Comportamiento:** Penaliza los errores de manera lineal, por lo que es **robusta ante outliers**. Sin embargo, su gradiente es discontinuo en el origen ($y_i = \hat{y}_i$), lo que puede causar oscilaciones alrededor del mínimo durante la optimización.

---

### 7.2. Para Tareas de Clasificación

#### Entropía Cruzada Binaria (*Binary Cross-Entropy* / *Log Loss*)
$$\mathcal{L}_{BCE} = -\frac{1}{n} \sum_{i=1}^n \left[ y_i \log(\hat{y}_i) + (1 - y_i) \log(1 - \hat{y}_i) \right]$$
donde $y_i \in \{0, 1\}$ es la etiqueta verdadera y $\hat{y}_i \in (0, 1)$ es la probabilidad predicha (típicamente salida de una función sigmoide).

* **Fundamento en Máxima Verosimilitud:** Deriva directamente de maximizar el logaritmo de la función de verosimilitud de una distribución de Bernoulli:
  $$P(Y = y \mid X = x) = \hat{y}^y (1 - \hat{y})^{1-y}$$
* **Propiedad asintótica:** Si $y_i = 1$ y $\hat{y}_i \to 0$, el término $\log(\hat{y}_i) \to -\infty$, por lo que la pérdida $\mathcal{L} \to \infty$. El modelo recibe un castigo masivo cuando predice con alta certeza una clase incorrecta.

---

## 8. Técnicas de Regularización

### 8.1. Formulación Matemática con Multiplicadores de Lagrange
El sobreajuste ocurre comúnmente cuando los pesos $W$ toman magnitudes excesivamente grandes para adaptarse al ruido de entrenamiento. El problema de optimización restringida:
$$\min_W \mathcal{L}(W) \quad \text{sujeto a} \quad \Omega(W) \le C$$
se reformula mediante el método de los multiplicadores de Lagrange como un problema no restringido:
$$W^* = \arg\min_W \left[ \mathcal{L}(W) + \lambda \Omega(W) \right]$$
donde $\lambda \ge 0$ es el hiperparámetro de regularización que pondera la penalización frente al error de ajuste.

---

### 8.2. Regularización $\mathcal{L}_2$ (*Weight Decay* / Norma de Frobenius)
Penaliza la suma de los cuadrados de los pesos (norma de Frobenius matricial $\|W\|_F^2$):
$$W^* = \arg\min_W \left[ \mathcal{L}(W) + \lambda \sum_i \sum_j w_{ij}^2 \right]$$

* **Efecto en la actualización del gradiente:**
  $$\nabla_W \mathcal{L}_{\text{total}} = \nabla_W \mathcal{L}(W) + 2\lambda W$$
  $$W_{t+1} = W_t - \alpha \left( \nabla_W \mathcal{L}(W_t) + 2\lambda W_t \right) = (1 - 2\alpha\lambda)W_t - \alpha \nabla_W \mathcal{L}(W_t)$$
  En cada iteración, el peso se contrae multiplicativamente por un factor $(1 - 2\alpha\lambda) < 1$.
* **Interpretación práctica:** Restringe el crecimiento de los pesos, forzando a la red a encontrar soluciones con coeficientes pequeños y distribuidos homogéneamente, lo que produce una función de mapeo suave y menos reactiva al ruido local.

---

### 8.3. Regularización $\mathcal{L}_1$ y el Fenómeno de Esparcidad (*Sparsity*)
Penaliza la suma de los valores absolutos de los pesos:
$$W^* = \arg\min_W \left[ \mathcal{L}(W) + \lambda \sum_i \sum_j |w_{ij}| \right]$$

* **Esparcidad (*Sparsity*):** A diferencia de $\mathcal{L}_2$, la norma $\mathcal{L}_1$ empuja muchos pesos **exactamente a cero**, actuando como un mecanismo automático de selección de características (*feature selection*).

---

### 8.4. Geometría de las Normas ($\ell_p$)
La forma de la bola unitaria $\{\mathbf{w} \in \mathbb{R}^2 : \|\mathbf{w}\|_p \le 1\}$ varía según el exponente $p$:

```
     Norma L1 (p=1)           Norma L2 (p=2)          Norma L_inf (p=inf)
          ▲                        ▲                        ▲
          │                        │                        │
       ___│___                  .──┴──.                  ┌──┴──┐
      /   │   \                /   │   \                 │  │  │
    ──┼───┼───┼──►           ──┼───┼───┼──►            ──┼───┼──┼──►
      \   │   /                \   │   /                 │  │  │
       ───┼───                  '──┬──'                  └──┬──┘
          │                        │                        │
  (Vértices en los ejes)       (Círculo liso)             (Cuadrado)
```

* **¿Por qué $\mathcal{L}_1$ induce esparcidad?**
  Las curvas de nivel de la función de pérdida $\mathcal{L}(W)$ se expanden elípticamente desde el mínimo no restringido. El punto de tangencia con la región de restricción ocurrirá casi siempre en una de las esquinas o vértices puntiagudos del rombo de $\mathcal{L}_1$, los cuales yacen exactamente sobre los ejes coordenados (donde una o más componentes son exactamente cero). En $\mathcal{L}_2$, al ser una esfera suave sin esquinas sobre los ejes, el punto de tangencia ocurre con altísima probabilidad en valores no nulos.

---

## 9. Optimizadores Modernos

El Descenso de Gradiente Estocástico puro experimenta dificultades en paisajes de pérdida patológicos, tales como barrancos donde la curvatura en una dirección es órdenes de magnitud mayor que en otra (mal condicionamiento del Hessiano).

```
Sin Momentum:                          Con Momentum:
▲ Oscilaciones transversales           ▲ Trayectoria amortiguada
│ \  / \  / \  /                       │ \
│  \/  \/  \/                          │  \───────────────►
│                                      │
└──────────────────────► Hacia el      └──────────────────► Rápido avance
                         mínimo                             hacia el mínimo
```

---

### 9.1. SGD con Momentum
Inspirado en la mecánica clásica: introduce una variable de inercia o momento que acumula las direcciones de gradiente pasadas:

$$m_{r+1} = \beta m_r + (1 - \beta) \sum_{i \in \mathcal{B}_r} \frac{\partial \ell_i(W_r)}{\partial W}$$
$$W_{r+1} = W_r - \alpha m_{r+1}$$

* $\beta \in [0, 1)$ es el factor de amortiguamiento (típicamente $\beta = 0.9$).
* **Efecto:** Las componentes oscilatorias perpendiculares con signos alternantes se cancelan, mientras que las componentes consistentes a lo largo del fondo del valle se suman y aceleran el desplazamiento.

---

### 9.2. Adam (*Adaptive Moment Estimation*)
Adam combina las ventajas de **Momentum** (acumulación de primer momento) y **RMSProp** (escalamiento por el segundo momento de los gradientes):

1. **Cálculo del gradiente en el paso $t$:** $g_t = \nabla_W \mathcal{L}(W_t)$
2. **Actualización del primer momento (media móvil del gradiente):**
   $$m_t = \beta_1 m_{t-1} + (1 - \beta_1) g_t$$
3. **Actualización del segundo momento (media móvil del cuadrado de los gradientes):**
   $$v_t = \beta_2 v_{t-1} + (1 - \beta_2) g_t^2$$
4. **Corrección de sesgo por inicialización en cero:**
   $$\hat{m}_t = \frac{m_t}{1 - \beta_1^t}, \quad \hat{v}_t = \frac{v_t}{1 - \beta_2^t}$$
5. **Actualización de pesos:**
   $$W_{t+1} = W_t - \frac{\alpha}{\sqrt{\hat{v}_t} + \epsilon} \hat{m}_t$$

* Valores estándar recomendados: $\alpha = 0.001$, $\beta_1 = 0.9$, $\beta_2 = 0.999$, $\epsilon = 10^{-8}$.
* **Ventaja clave:** Proporciona una tasa de aprendizaje adaptativa individual para cada parámetro: parámetros con gradientes infrecuentes o pequeños reciben actualizaciones mayores, mientras que parámetros con gradientes volátiles reciben actualizaciones controladas.

---

## 10. Heurísticas Fundamentales de Entrenamiento

### 10.1. Parada Temprana (*Early Stopping*)
Consiste en monitorear continuamente el error en el conjunto de validación en cada época. El entrenamiento se detiene automáticamente cuando el error de validación deja de decrecer tras un número predefinido de épocas consecutivas (*patience*).

* **Fundamento:** Se guardan los pesos correspondientes a la época con menor error de validación.
* **Propiedad teórica:** Actúa como una forma de regularización implícita, limitando la distancia euclidiana que los pesos pueden recorrer desde su inicialización en el espacio de parámetros.

---

### 10.2. Dropout
Durante cada iteración de entrenamiento, cada neurona de las capas ocultas se desactiva temporalmente (su valor se anula, $a_j = 0$) con una probabilidad $p$ (usualmente $p = 0.5$ en capas densas, $p = 0.1-0.2$ en capas de entrada):

```
Paso de entrenamiento 1:                 Paso de entrenamiento 2:
   (x1) ───> (h1) [X] ───> (y)              (x1) ───> (h1) ───────> (y)
   (x2) ───> (h2) ───────> (y)              (x2) [X]  (h2) [X] ───> (y)
   (x3) ───> (h3) ───────> (y)              (x3) ───> (h3) ───────> (y)
```

* **Beneficios teóricos:**
  1. **Evita la co-adaptación:** Las neuronas no pueden depender de la presencia constante de neuronas vecinas específicas para corregir sus errores, obligando a cada una a aprender características más representativas e independientes.
  2. **Efecto Ensamble (*Model Ensemble*):** Entrenar con dropout equivale a entrenar un ensamble de $2^N$ subredes diferentes con pesos compartidos.
* **Fase de Inferencia:** En tiempo de prueba/producción, todas las neuronas permanecen activas. Para mantener la misma escala de magnitud en las activaciones, las salidas se multiplican por $(1 - p)$ (o equivalentemente se aplica *Inverted Dropout* dividiendo por $1-p$ durante el entrenamiento).

---

## 11. El "Zoológico" de Arquitecturas Neuronales

Dependiendo de las invariancias matemáticas y la estructura de los datos, se seleccionan distintas familias de redes:

```
                              ┌─────────────────────────────────┐
                              │    ¿Qué estructura tienen       │
                              │        los datos?               │
                              └───────────────┬─────────────────┘
                                              │
         ┌──────────────────┬─────────────────┴─────────────────┬──────────────────┐
         ▼                  ▼                                   ▼                  ▼
   [Tabulares]         [Imágenes/2D]                      [Secuencias/1D]     [Relaciones/Grafos]
   Vectores densos     Invariancia a traslación           Series temporales   Nodos y aristas
         │                  │                                   │                  │
      ┌──┴──┐            ┌──┴──┐                             ┌──┴──┐            ┌──┴──┐
      │ MLP │            │ CNN │                             │ RNN │            │ GNN │
      └─────┘            └─────┘                             └─────┘            └─────┘
                                                          (LSTM, GRU,
                                                          Transformers)
```

1. **MLP (Perceptrón Multicapa / Capas Densas):** Conectividad total sin supuestos espaciales.
2. **CNN (Redes Convolucionales):** Explotan localidad espacial y equivariancia a la traslación mediante filtros compartidos (visión por computadora).
3. **RNN / LSTM / GRU:** Diseñadas para dependencias temporales y secuencias con estados recurrentes.
4. **Transformers (Atención Multi-Cabeza):** Modelan correlaciones arbitrarias de largo alcance en paralelo sin depender de recurrencia secuencial.

---

## 12. Implementación Práctica de un Perceptrón en Frameworks Modernos

Ejemplo de implementación de un clasificador binario simple (Perceptrón con salida sigmoidal, función de pérdida de entropía cruzada y optimizador SGD con momentum):

### 12.1. MATLAB
```matlab
% 1. Definición del modelo con 1 capa y algoritmo traingdm (SGD con momentum)
net = feedforwardnet(1, 'traingdm');
net.layers{1}.transferFcn = 'logsig'; % Función de activación sigmoide

% 2. Hiperparámetros de entrenamiento
net.performFcn = 'crossentropy';     % Pérdida de entropía cruzada
net.trainParam.epochs = 100;         % Cantidad de épocas
net.trainParam.lr = 0.1;             % Tasa de aprendizaje (learning rate)
net.trainParam.mc = 0.9;             % Coeficiente de momentum

% 3. Entrenamiento del modelo
net = train(net, X_train, y_train);

% 4. Inferencia
y_hat = net(X);
```

---

### 12.2. TensorFlow + Keras (Python)
```python
import tensorflow as tf
from tensorflow.keras import Sequential
from tensorflow.keras.layers import Dense
from tensorflow.keras.optimizers import SGD

# 1. Definición secuencial del modelo
model = Sequential()
model.add(Dense(1, activation='sigmoid', input_shape=(input_dim,)))

# 2. Configuración de hiperparámetros y compilación
opt = SGD(learning_rate=0.1, momentum=0.9)
model.compile(
    loss='binary_crossentropy',
    optimizer=opt,
    metrics=['accuracy']
)

# 3. Entrenamiento
history = model.fit(
    X_train, y_train,
    validation_data=(X_val, y_val),
    epochs=100,
    batch_size=32
)

# 4. Inferencia
y_hat = model.predict(X)
```

---

### 12.3. PyTorch (Python)
```python
import torch
import torch.nn as nn
import torch.optim as optim

# 1. Definición de la clase de red como módulo de PyTorch
class SimplePerceptron(nn.Module):
    def __init__(self, input_size):
        super(SimplePerceptron, self).__init__()
        self.output_layer = nn.Linear(input_size, 1)

    def forward(self, x):
        z = self.output_layer(x)
        y_hat = torch.sigmoid(z)
        return y_hat

# 2. Instanciación y definición de optimizador y función de pérdida
input_dim = 10
model = SimplePerceptron(input_size=input_dim)
criterion = nn.BCELoss()
optimizer = optim.SGD(model.parameters(), lr=0.1, momentum=0.9)

# 3. Bucle de entrenamiento explícito
epochs = 100
for epoch in range(epochs):
    model.train()
    optimizer.zero_grad()            # Reiniciar gradientes acumulados
    predictions = model(X_train)     # Forward pass
    loss = criterion(predictions, y_train)  # Calcular pérdida
    loss.backward()                  # Backward pass (autograd)
    optimizer.step()                 # Actualización de pesos

# 4. Inferencia
model.eval()
with torch.no_grad():
    y_hat = model(X_test)
```

---

## 13. Resumen Sintético de Conceptos Clave

```
┌─────────────────────────┬─────────────────────────────────────────────────────────────────────────┐
│ Concepto                │ Resumen Operativo                                                       │
├─────────────────────────┼─────────────────────────────────────────────────────────────────────────┤
│ Teorema de Aprox. Univ. │ 1 capa oculta aproxima cualquier función continua, pero puede requerir  │
│                         │ neuronas infinitas. La profundidad aporta eficiencia exponencial.       │
├─────────────────────────┼─────────────────────────────────────────────────────────────────────────┤
│ Expresividad (ReLU)     │ Una red profunda con K capas particiona el espacio en hasta (D+1)^K     │
│                         │ regiones lineales continuas, frente a solo D+1 en una red superficial.  │
├─────────────────────────┼─────────────────────────────────────────────────────────────────────────┤
│ Mini-Batch SGD          │ Promedia gradientes sobre un lote aleatorio B, permitiendo aceleración   │
│                         │ por GPU y escape estocástico de puntos de ensilladura.                  │
├─────────────────────────┼─────────────────────────────────────────────────────────────────────────┤
│ Train / Val / Test      │ Train (aprende W), Val (ajusta hiperparámetros), Test (evaluación final │
│                         │ no sesgada). Evitar fuga de datos a toda costa.                         │
├─────────────────────────┼─────────────────────────────────────────────────────────────────────────┤
│ Overfitting vs Underf.  │ Overfitting = Alta Varianza (Train Loss baja, Val Loss diverge).         │
│                         │ Underfitting = Alto Sesgo (Train y Val Loss altas).                     │
├─────────────────────────┼─────────────────────────────────────────────────────────────────────────┤
│ Regularización L2 / L1  │ L2 (Frobenius) contrae pesos y suaviza la función.                      │
│                         │ L1 (Lasso) promueve escasez (pesos exactamente cero).                   │
├─────────────────────────┼─────────────────────────────────────────────────────────────────────────┤
│ Momentum y Adam         │ Momentum amortigua oscilaciones ortogonales en cañones.                 │
│                         │ Adam adapta la tasa de aprendizaje individualmente por parámetro.       │
├─────────────────────────┼─────────────────────────────────────────────────────────────────────────┤
│ Dropout & Early Stop    │ Dropout apaga neuronas al azar para evitar co-adaptación (ensamble).    │
│                         │ Early Stopping detiene el proceso cuando la Val Loss se degrada.        │
└─────────────────────────┴─────────────────────────────────────────────────────────────────────────┘
```

---

## 14. Bibliografía
1. **Prince, Simon J. D.** *Understanding Deep Learning*. MIT Press, 2023.
   * Capítulo 4: *Shallow neural networks to deep neural networks*.
   * Capítulo 5: *Loss functions*.
   * Capítulo 6: *Fitting models & optimization*.
   * Capítulo 9: *Regularization*.
2. **Goodfellow, Ian; Bengio, Yoshua; Courville, Aaron.** *Deep Learning*. MIT Press, 2016.
3. **Cybenko, George.** *Approximation by superpositions of a sigmoidal function*. Mathematics of Control, Signals and Systems, 2(4), 303-314, 1989.

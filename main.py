from gurobipy import GRB, Model, quicksum
import pandas as pd

# Cargar archivo Excel

archivo = "bd_opti.xlsx"
# Usando ruta completa
archivo = r"C:\Users\ignac\OneDrive\Desktop\e2_opti\bd_opti.xlsx"
hojas = pd.ExcelFile(archivo).sheet_names


# Cargar hojas específicas

zonas_df = pd.read_excel(archivo, sheet_name="zonas")
regadores_df = pd.read_excel(archivo, sheet_name="regadores")
activaciones_df = pd.read_excel(archivo, sheet_name="costos_activacion")
iniciales_df = pd.read_excel(archivo, sheet_name="regadores_iniciales")
capacidad_df = pd.read_excel(archivo, sheet_name="capacidad_agua")
no_permitidas_df = pd.read_excel(archivo, sheet_name="horas_no_permitidas")

# CONJUNTOS ----------------------------------------------------------------

R = regadores_df["regador"].unique().tolist()
N = zonas_df["zona"].unique().tolist()
T = list(range(24))
'''
H = 6  # Puedes cambiar esto según cuántos días estés modelando
D = list(range(H + 1))
'''
Th = no_permitidas_df["hora"].tolist()

print("Conjuntos listos")

# PARAMETROS ------------------------------------------------------------


# Zonas
# zona	area_m2 (An)	litros_prom (Jn)	max_horas (Ln)	agua_inicial (Qn)	agua_min (Aminn)	agua_max (Amaxn)	costo_replantar (C area n)
An = dict(zip(zonas_df["zona"], zonas_df["area_m2 (An)"]))
Jn = dict(zip(zonas_df["zona"], zonas_df["litros_prom (Jn)"]))
Ln = dict(zip(zonas_df["zona"], zonas_df["max_horas (Ln)"]))
Qn = dict(zip(zonas_df["zona"], zonas_df["agua_inicial (Qn)"]))
Aminn = dict(zip(zonas_df["zona"], zonas_df["agua_min (Aminn)"]))
Amaxn = dict(zip(zonas_df["zona"], zonas_df["agua_max (Amaxn)"]))
Carean = dict(zip(zonas_df["zona"], zonas_df["costo_replantar (C area n)"]))

# Regadores
#regador	area_cubre_m2 (Fr)	costo_instalacion (Cr)	costo_mant (Er)	costo_remocion (Sr)	eficiencia (βr)	litros_hora (Cant r)
Fr = dict(zip(regadores_df["regador"], regadores_df["area_cubre_m2 (Fr)"]))
Cr = dict(zip(regadores_df["regador"], regadores_df["costo_instalacion (Cr)"]))
Er = dict(zip(regadores_df["regador"], regadores_df["costo_mant (Er)"]))
Sr = dict(zip(regadores_df["regador"], regadores_df["costo_remocion (Sr)"]))
βr = dict(zip(regadores_df["regador"], regadores_df["eficiencia (βr)"]))
Cantr = dict(zip(regadores_df["regador"], regadores_df["litros_hora (Cant r)"]))

# Costos de activación riego r en zona n
#regador	zona	costo_activacion (Hrn)
Hrn = {(row["regador"], row["zona"]): row["costo_activacion (Hrn)"] for _, row in activaciones_df.iterrows()}

# Regadores iniciales
#regador	zona	cantidad_inicial (Rrn)
Rrn = {(row["regador"], row["zona"]): row["cantidad_inicial (Rrn)"] for _, row in iniciales_df.iterrows()}

# Capacidad máxima de agua por hora
#hora	capacidad_litros (Dt)
Dt = dict(zip(capacidad_df["hora"], capacidad_df["capacidad_litros (Dt)"]))

# Parametros globales

K = 15         # Costo por litro
Mbig = 10000   # Valor grande para restricciones
U = 2          # Días de instalación
U_minus = 1    # Días de remoción
Umax = 10      # Tiempo máximo entre instalación y remoción


print("Parametros listos")



# MODELO ----------------------------------------------------------------



m = Model("Optimizacion del sistema de riego agrícola")
m.setParam("TimeLimit", 2 * 60)

# VARIABLES -------------------------------------------------------------

# Inventario de regadores r en zona n al tiempo t
Yrnt = m.addVars(R, N, T, vtype=GRB.INTEGER, name="Yrnt")

# Si se riega con regador r en zona n al tiempo t (variable binaria)
Zrnt = m.addVars(R, N, T, vtype=GRB.BINARY, name="Zrnt")

# Regadores comprados
Vrnt = m.addVars(R, N, T, vtype=GRB.INTEGER, name="Vrnt")

# Regadores quitados
Vminus_rnt = m.addVars(R, N, T, vtype=GRB.INTEGER, name="Vminus_rnt")

# Condición de regador r en zona n (binaria, puede significar si está activo)
Condrn = m.addVars(R, N, vtype=GRB.BINARY, name="Condrn")   # ver si es necesario agregar t

# Litros de agua regados con regador r en zona n al tiempo t
Xnrt = m.addVars(N, R, T, vtype=GRB.CONTINUOUS, name="Xnrt")

# Cantidad de agua disponible en el suelo en zona n al tiempo t
Int = m.addVars(N, T, vtype=GRB.CONTINUOUS, name="Int")

# Error de agua (por exceso o falta de riego)
Wnt = m.addVars(N, T, vtype=GRB.CONTINUOUS, name="Wnt")

# FUNCIÓN OBJETIVO -----------------------------------------------------

# Minimizar costos totales: instalación, remoción, mantenimiento, activación, agua y errores
obj = quicksum(
    Vrnt[r, n, t] * Cr[r] +                # Costo de comprar regadores
    Vminus_rnt[r, n, t] * Sr[r] +           # Costo de remover regadores
    Yrnt[r, n, t] * Er[r] +                 # Costo de mantenimiento
    Zrnt[r, n, t] * Hrn[r, n] +             # Costo de activación
    Xnrt[n, r, t] * K +                     # Costo del agua utilizada
    Wnt[n, t] * Carean[n]                   # Costo por errores de riego
    for r in R for n in N for t in T
)

m.setObjective(obj, GRB.MINIMIZE)

print("Función objetivo establecida")

# RESTRICCIONES --------------------------------------------------------

print("Agregando restricciones...")

# 1. Balance hídrico mínimo (no permitir que el agua en suelo sea menor que Aminn - error)
m.addConstrs(
    (Int[n, t] >= Aminn[n] - Wnt[n, t] 
     for n in N for t in T),
    name="min_water"
)

# 2. Balance hídrico máximo (no permitir que el agua en suelo sea mayor que Amaxn + error)
m.addConstrs(
    (Int[n, t] <= Amaxn[n] + Wnt[n, t] 
     for n in N for t in T),
    name="max_water"
)

# 3. Balance de agua para t > 0
m.addConstrs(
    (Int[n, t] == quicksum(Xnrt[n, r, t] * βr[r] for r in R) + Int[n, t-1] - Jn[n]
    for n in N for t in range(1, 24)),
    name="water_balance"
)

# 4. Condición inicial de agua (t=0)
m.addConstrs(
    (Int[n, 0] == quicksum(Xnrt[n, r, 0] * βr[r] for r in R) - Jn[n] + Qn[n]
    for n in N),
    name="initial_water"
)

# 5. Relación entre Zrnt y Yrnt (solo se puede regar si hay regadores disponibles)
m.addConstrs(
    (Zrnt[r, n, t] <= Mbig * Yrnt[r, n, t]
     for r in R for n in N for t in T),
    name="Z_Y_relation"
)

# 6. Activar Zrnt si se usa el riego r
m.addConstrs(
    (Mbig * Zrnt[r, n, t] >= Xnrt[n, r, t]
     for r in R for n in N for t in T),
    name="activate_Z"
)

# 7. Control de inventario de regadores (para t > 0)
m.addConstrs(
    (Yrnt[r, n, t] == Yrnt[r, n, t-1] + Vrnt[r, n, t-U] - Vminus_rnt[r, n, t-U_minus]
     for r in R for n in N for t in range(Umax, 24)),
    name="inventory_control"
)

# 8. Inventario inicial de regadores (para t < Umax)
m.addConstrs(
    (Yrnt[r, n, t] == Rrn[r, n]
     for r in R for n in N for t in range(U)),
    name="initial_inventory"
)

# 9. Prohibir riego durante horas no permitidas
m.addConstrs(
    (quicksum(Zrnt[r, n, t] for r in R for n in N) == 0
     for t in Th),
    name="no_irrigation_hours"
)

# 10. Relación entre regadores disponibles y capacidad de riego
m.addConstrs(
    (Yrnt[r, n, t] * Cantr[r] >= Xnrt[n, r, t]
     for r in R for n in N for t in T),
    name="regador_capacity"
)

# 11. Restricción de capacidad total de agua por hora
m.addConstrs(
    (quicksum(Xnrt[n, r, t] for n in N for r in R) <= Dt[t]
     for t in T),
    name="total_water_capacity"
)

# 12. No superar horas máximas consecutivas de riego por zona
for n in N:
    max_horas = Ln[n]
    for t in range(24 - max_horas):
        m.addConstr(
            quicksum(Zrnt[r, n, k] for r in R for k in range(t, t + max_horas + 1)) <= max_horas,
            name=f"max_consec_hours_{n}_{t}"
        )

print("Restricciones agregadas")

# OPTIMIZAR ------------------------------------------------------------

m.optimize()

# RESULTADOS -----------------------------------------------------------

if m.status == GRB.OPTIMAL:
    print("\nSolución óptima encontrada")
    print(f"Costo total: {m.objVal:,.2f} CLP")
    
    # Mostrar compras de regadores
    print("\nCompras de regadores:")
    for t in T:
        for r in R:
            for n in N:
                if Vrnt[r, n, t].X > 0:
                    print(f"Hora {t}: Comprar {Vrnt[r, n, t].X} regadores {r} para zona {n}")
    
    # Mostrar remociones de regadores
    print("\nRemociones de regadores:")
    for t in T:
        for r in R:
            for n in N:
                if Vminus_rnt[r, n, t].X > 0:
                    print(f"Hora {t}: Remover {Vminus_rnt[r, n, t].X} regadores {r} de zona {n}")
    
    # Mostrar agua utilizada por hora
    print("\nAgua utilizada por hora:")
    for t in T:
        total_agua = sum(Xnrt[n, r, t].X for n in N for r in R)
        print(f"Hora {t}: {total_agua:,.2f} litros")
    
    # Mostrar errores de riego
    print("\nErrores de riego (excesos o déficits):")
    for n in N:
        for t in T:
            if Wnt[n, t].X > 0:
                print(f"Zona {n}, hora {t}: Error de {Wnt[n, t].X:.2f} litros")
    
else:
    print("No se encontró solución óptima")
    print(f"Estado del modelo: {m.status}")
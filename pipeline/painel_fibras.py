#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# dependencies = ["numpy", "tifffile", "pillow", "scipy", "imagecodecs"]
# ///
"""
painel_fibras.py — monta painel de calibracao para o gate de fibras.

PROBLEMA QUE ESTE SCRIPT RESOLVE
--------------------------------
"As fibras correm horizontais?" e' dificil de responder no absoluto. O criterio
do premio e' visual e comparativo por natureza:

  "check if you can visually follow horizontal papyrus fibers across the page —
   this is an indication the segmentation is good (and not jumping between
   sheets)"  [scrollprize.org/prizes, Grand Prize]

Calibracao do Discord (Hari Seldon, 18/08): letras tem ~3-4 fibras de altura e
largura. Letras nesses rolos tem ~2-4 mm, logo uma fibra tem ~0,6-1,3 mm, que a
8,64 um sao ~70-150 px. FIBRA E' FAIXA LARGA, NAO ESTRIA FINA. Papiro e' trama:
tiras horizontais de um lado, verticais do outro; o que confirma folha unica e'
ver o XADREZ.

Entao o painel poe lado a lado uma referencia CONHECIDAMENTE BOA e a incognita,
na mesma escala fisica. A pergunta vira "o da direita se parece com o da
esquerda?", que e' mais confiavel que julgamento absoluto.

REFERENCIA: renders/oficial_w00_full.tif — render OFICIAL da equipe do w00 do
PHercParis4 a 9,362 um. E' o insumo de onde saem as letras que todos leem.
Passa no criterio por construcao.

DECISOES DECLARADAS (todas afetam o julgamento; nenhuma e' neutra)
-----------------------------------------------------------------
1. ESCALA. A referencia e' reamostrada de 9,362 para 8,64 um/px (fator 1,0836)
   para que 1 px signifique a mesma distancia fisica nos dois lados. Sem isso a
   fibra do 1447 pareceria 8% maior e o olho registraria diferenca inexistente.
2. ESCOLHA DE JANELA. Nos DOIS lados a janela e' escolhida pelo mesmo criterio
   mecanico: maior cobertura de pixels nao-zero. Nao escolho a olho, para nao
   favorecer nenhum dos lados. A posicao escolhida e' impressa.
3. NORMALIZACAO CONJUNTA. Percentis calculados sobre os dois recortes JUNTOS e
   o mesmo mapeamento aplicado aos dois. Normalizar cada um por si faria a
   diferenca de aparencia vir da normalizacao, nao do substrato.
4. RESOLUCAO PLENA. Sem reducao. Miniaturas ja causaram quatro leituras erradas
   numa semana neste projeto.
5. REFERENCIA ROTULADA, NAO CEGA. Isto e' calibracao do olho, nao teste de
   hipotese. Cegar aqui confundiria treinar com testar.

USO
---
  uv run painel_fibras.py
  uv run painel_fibras.py --win 2048 --alvo z_dbg
"""

import argparse
import pathlib

import numpy as np
import tifffile
from PIL import Image, ImageDraw
from scipy.ndimage import zoom as ndzoom

Image.MAX_IMAGE_PIXELS = None

UM_REF = 9.362      # 1667 w013
UM_ALVO = 9.362      # PHerc0826


def melhor_janela(m: np.ndarray, win: int, passo: int):
    """Janela [win x win] de maior fracao nao-zero. Busca grosseira por passo."""
    H, W = m.shape
    if H < win or W < win:
        raise SystemExit(f"imagem {m.shape} menor que a janela {win}")
    best = (-1.0, 0, 0)
    for y in range(0, H - win + 1, passo):
        for x in range(0, W - win + 1, passo):
            c = float(m[y:y + win, x:x + win].mean())
            if c > best[0]:
                best = (c, y, x)
    return best


def main():
    ap = argparse.ArgumentParser()
    home = pathlib.Path.home()
    ap.add_argument("--ref", default=str(home / "challenges/vesuvius/villa_ink/"
                    "ink-detection/renders/oficial_w00_full.tif"))
    ap.add_argument("--alvo", default="z_dbg")
    ap.add_argument("--base", default=str(home / "challenges/vesuvius/ink-lens/"
                    "gate_fibras_1447"))
    ap.add_argument("--win", type=int, default=2048,
                    help="lado da janela em px do ALVO (8,64 um)")
    ap.add_argument("--passo", type=int, default=512)
    ap.add_argument("--out", default=None)
    args = ap.parse_args()

    base = pathlib.Path(args.base)
    alvo_tif = next(iter(sorted((base / args.alvo).glob("*_mid*.tif"))), None)
    if alvo_tif is None:
        raise SystemExit(f"nao achei *_mid*.tif em {base/args.alvo}")

    win = args.win
    lado_mm = win * UM_ALVO * 1e-3
    print(f"janela: {win} px @ {UM_ALVO} um = {lado_mm:.1f} mm de lado "
          f"({(lado_mm/10)**2:.2f} cm²)")

    # ---------------- alvo
    print(f"\n[alvo] {alvo_tif.name}")
    A = tifffile.imread(str(alvo_tif))
    ca, ya, xa = melhor_janela(A > 0, win, args.passo)
    print(f"  shape {A.shape}  melhor janela y={ya} x={xa} cobertura={ca:.1%}")
    crop_a = A[ya:ya + win, xa:xa + win].astype(np.float32)

    # ---------------- referencia (reamostrada para a escala do alvo)
    print(f"\n[ref] {pathlib.Path(args.ref).name}  ({UM_REF} um)")
    R = tifffile.imread(args.ref)
    fator = UM_REF / UM_ALVO          # >1: a ref precisa ser AMPLIADA
    win_ref = int(round(win / fator))  # janela em px da ref que cobre a mesma area
    print(f"  shape {R.shape}  fator escala {fator:.4f}  "
          f"janela na ref = {win_ref} px")
    cr, yr, xr = melhor_janela(R > 0, win_ref, args.passo)
    print(f"  melhor janela y={yr} x={xr} cobertura={cr:.1%}")
    crop_r = R[yr:yr + win_ref, xr:xr + win_ref].astype(np.float32)
    crop_r = ndzoom(crop_r, win / win_ref, order=1)
    if crop_r.shape != (win, win):     # arredondamento
        crop_r = crop_r[:win, :win]
        if crop_r.shape != (win, win):
            pad = [(0, win - crop_r.shape[0]), (0, win - crop_r.shape[1])]
            crop_r = np.pad(crop_r, pad)
    print(f"  reamostrada para {crop_r.shape}")

    # ---------------- normalizacao CONJUNTA
    juntos = np.concatenate([crop_r[crop_r > 0].ravel(),
                             crop_a[crop_a > 0].ravel()])
    lo, hi = np.percentile(juntos, [1.0, 99.0])
    print(f"\n[norm] conjunta sobre os dois: p1={lo:.1f} p99={hi:.1f}")

    def norm(t):
        n = np.clip((t - lo) / max(1e-6, hi - lo), 0, 1)
        n[t == 0] = 0
        return (n * 255).astype(np.uint8)

    ir, ia = norm(crop_r), norm(crop_a)

    # ---------------- painel
    gap, top = 16, 40
    im = Image.new("L", (2 * win + 3 * gap, win + top + gap), 20)
    d = ImageDraw.Draw(im)
    im.paste(Image.fromarray(ir), (gap, top))
    im.paste(Image.fromarray(ia), (2 * gap + win, top))
    d.text((gap + 4, 12), f"REFERENCIA  PHerc1667 w013 (lido, {UM_REF} um "
           f"-> {UM_ALVO})   cob={cr:.0%}  y={yr} x={xr}", fill=255)
    d.text((2 * gap + win + 4, 12), f"ALVO  {args.alvo} ({UM_ALVO} um)"
           f"   cob={ca:.0%}  y={ya} x={xa}", fill=255)

    out = args.out or str(base / f"painel_{args.alvo}_{win}.png")
    im.save(out)
    print(f"\nsalvo: {out}  ({im.size[0]}x{im.size[1]})")
    print("\nO QUE JULGAR — o criterio e' do premio, nao nosso:")
    print("  Da para SEGUIR fibras horizontais atravessando a pagina?")
    print("  Espere FAIXAS LARGAS (~70-150 px), nao estria fina.")
    print("  Espere TRAMA (xadrez: horizontais x verticais cruzando).")
    print("  REPROVA: redemoinho fechado, linha ondulada em corte transversal,")
    print("           blocos retangulares, fibra correndo em diagonal.")
    print("\nA pergunta pratica: o da DIREITA se parece com o da ESQUERDA?")


if __name__ == "__main__":
    main()

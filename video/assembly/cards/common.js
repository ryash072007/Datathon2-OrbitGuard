// Deterministic helpers: every card exposes window.render(t) as a pure function of time t (seconds).
function rng(seed){let a=seed>>>0;return function(){a|=0;a=a+0x6D2B79F5|0;let t=Math.imul(a^a>>>15,1|a);t=t+Math.imul(t^t>>>7,61|t)^t;return((t^t>>>14)>>>0)/4294967296}}
const clamp=(x,a=0,b=1)=>Math.min(b,Math.max(a,x));
const easeOut=x=>1-Math.pow(1-clamp(x),3);
const easeIO=x=>{x=clamp(x);return x<.5?4*x*x*x:1-Math.pow(-2*x+2,3)/2};
const seg=(t,t0,d)=>clamp((t-t0)/d);
function makeBg(canvas,opts={}){
  const ctx=canvas.getContext('2d');canvas.width=1920;canvas.height=1080;
  const R=rng(opts.seed||7),stars=[];
  for(let i=0;i<260;i++)stars.push({x:R()*1920,y:R()*1080,r:.4+R()*1.5,p:R()*6.28,s:.4+R()*1.6,d:.2+R()*.8});
  const orbits=[{rx:820,ry:250,rot:-.35,ph:0,sp:.35},{rx:640,ry:190,rot:.5,ph:2,sp:-.5},{rx:980,ry:330,rot:.12,ph:4,sp:.22}];
  const cx=opts.cx??960,cy=opts.cy??540,dim=opts.dim??1;
  return function(t){
    ctx.clearRect(0,0,1920,1080);
    const g=ctx.createRadialGradient(cx,cy,50,cx,cy,1100);g.addColorStop(0,'#0b1a30');g.addColorStop(1,'#03060d');
    ctx.fillStyle=g;ctx.fillRect(0,0,1920,1080);
    for(const s of stars){
      const x=(s.x+t*6*s.d)%1920,tw=.55+.45*Math.sin(t*s.s+s.p);
      ctx.fillStyle=`rgba(200,225,255,${(.15+.6*s.d)*tw*dim})`;ctx.beginPath();ctx.arc(x,s.y,s.r,0,6.283);ctx.fill();
    }
    for(const o of orbits){
      ctx.save();ctx.translate(cx,cy);ctx.rotate(o.rot+t*.01);
      ctx.strokeStyle=`rgba(56,214,245,${.16*dim})`;ctx.lineWidth=1.5;ctx.beginPath();ctx.ellipse(0,0,o.rx,o.ry,0,0,6.283);ctx.stroke();
      const a=o.ph+t*o.sp,px=Math.cos(a)*o.rx,py=Math.sin(a)*o.ry;
      for(let k=1;k<26;k++){const b=a-k*.022*Math.sign(o.sp);ctx.fillStyle=`rgba(56,214,245,${(.5*(1-k/26))*dim})`;ctx.beginPath();ctx.arc(Math.cos(b)*o.rx,Math.sin(b)*o.ry,3.2*(1-k/40),0,6.283);ctx.fill()}
      ctx.shadowColor='#38d6f5';ctx.shadowBlur=18;ctx.fillStyle='#bff3ff';ctx.beginPath();ctx.arc(px,py,5,0,6.283);ctx.fill();
      ctx.restore();
    }
  };
}
